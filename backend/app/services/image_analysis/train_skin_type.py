"""Fine-tune EfficientNet-B0 to predict skin type from the aligned face (step 7a, Part 3).

Run from backend/ after `pip install -r requirements-train.txt`, with both Kaggle
datasets unzipped into datasets/ (README.md, "Skin-type classifier"):

    python -m app.services.image_analysis.train_skin_type              # full run
    python -m app.services.image_analysis.train_skin_type --dedup-only # grouping + split report only
    python -m app.services.image_analysis.train_skin_type --fresh      # recompute everything

Pipeline: check the GPU -> discover images -> group duplicate copies -> drop groups with
conflicting labels -> 70/15/15 split by group (stratified by label) -> face crops made by
the live service's own detector/aligner -> fine-tune -> evaluate once on the untouched
test split -> weights/ + report. Seeded, so a re-run reproduces the split exactly and the
model up to GPU floating-point non-determinism.

Writes (all gitignored): weights/skin_type_efficientnet_b0.pt, weights/skin_type_report.md,
weights/skin_type_report.json, weights/skin_type_split.json, datasets/_cache/,
datasets/_reports/dedup_sample_pairs.jpg.
"""

import argparse
import hashlib
import json
import random
import sys
import time
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path

import cv2
import numpy as np

from . import scoring_config as cfg
from . import skin_type_data as data
from .analyzer import SERVICE_DIR, load_models
from .errors import ImageRejected
from .face import align_face
from .lighting import measure as measure_lighting
from .lighting import tone_group
from .scoring import build_maps
from .skin_type import (
    IMAGENET_MEAN,
    IMAGENET_STD,
    INPUT_SIZE,
    WEIGHTS_DIR,
    WEIGHTS_PATH,
    classifier_input,
)

DATASETS_DIR = SERVICE_DIR / "datasets"
LABELS = list(data.LABELS)
# Skin-tone breakdown: plain ITA (from absolute L*) is unusable on web photos (halving the
# exposure moved one face from 65 to -21 degrees), so skin luminance is measured relative
# to a white reference in the same photo instead: see lighting.py and README.md.


def log(*parts) -> None:
    print(*parts, flush=True)


# ----------------------------------------------------------------------------------------
# Setup
# ----------------------------------------------------------------------------------------


def check_gpu(allow_cpu: bool) -> str:
    import torch

    if not torch.cuda.is_available():
        if allow_cpu:
            log("No CUDA GPU: training on CPU (slow).")
            return "cpu"
        sys.exit(
            "CUDA is not available. Install the GPU build (pip install -r requirements-train.txt) "
            "or pass --allow-cpu."
        )
    a, b = torch.randn(512, 512), torch.randn(512, 512)
    error = ((a.cuda() @ b.cuda()).cpu() - a @ b).abs().max().item()
    props = torch.cuda.get_device_properties(0)
    log(
        f"GPU: {props.name}, sm_{props.major}{props.minor}, {props.total_memory / 2**30:.1f} GB; "
        f"torch {torch.__version__}; test matmul max |gpu - cpu| = {error:.1e}"
    )
    if error > 1e-2:
        sys.exit("GPU result disagrees with CPU; refusing to train.")
    return "cuda"


def seed_everything(seed: int) -> None:
    import torch

    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.backends.cudnn.benchmark = False


def downscale(bgr: np.ndarray) -> np.ndarray:
    """The same size cap the live service applies after decoding."""
    longest = max(bgr.shape[:2])
    if longest <= cfg.WORKING_MAX_SIDE:
        return bgr
    scale = cfg.WORKING_MAX_SIDE / longest
    return cv2.resize(bgr, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)


# ----------------------------------------------------------------------------------------
# Per-image signatures (cached)
# ----------------------------------------------------------------------------------------


def compute_signatures(records, analyzer, device: str, data_dir: Path, fresh: bool):
    """(pHash, CNN embeddings, face widths, ORB features) for every record.

    The slow parts (CNN embedding, face detection) are cached in _cache/; pHash and ORB
    are recomputed every run (one pass over the images), so they always reflect the
    current dedup settings in skin_type_data.py.
    """
    paths = [str(r.path.relative_to(data_dir)) for r in records]
    cache = data_dir / "_cache" / "signatures.npz"
    cached = None
    if cache.is_file() and not fresh:
        saved = np.load(cache, allow_pickle=False)
        if list(saved["paths"]) == paths and "embeddings" in saved:
            cached = (saved["embeddings"], saved["face_width"])
            log(f"Reusing cached CNN embeddings and face sizes ({cache.name}).")

    log(
        f"Computing pHash and ORB{'' if cached else ', CNN embedding and face size'} for {len(records)} images..."
    )
    started = time.perf_counter()
    hashes, widths, orb, squares, embeddings = [], [], [], [], []
    for index, record in enumerate(records):
        image = data.read_image(record.path)
        if image is None:
            sys.exit(f"Unreadable image: {record.path}")
        hashes.append(data.phash_dihedral(data.content_crop(image)))
        orb.append(data.orb_features(image))
        if cached is None:
            faces = analyzer.face_detector.detect(downscale(image))
            widths.append(faces[0].width if faces else 0.0)
            squares.append(image)
            if len(squares) == 256 or index == len(records) - 1:
                embeddings.append(data.cnn_embeddings(squares, device))
                squares = []
        if (index + 1) % 512 == 0 or index == len(records) - 1:
            log(f"  {index + 1}/{len(records)}  ({time.perf_counter() - started:.0f} s)")
    if cached is None:
        emb, face_width = np.concatenate(embeddings), np.array(widths)
        cache.parent.mkdir(parents=True, exist_ok=True)
        np.savez(cache, paths=np.array(paths), embeddings=emb, face_width=face_width)
    else:
        emb, face_width = cached
    return np.stack(hashes), emb, face_width, orb


# ----------------------------------------------------------------------------------------
# Dedup report
# ----------------------------------------------------------------------------------------


def report_grouping(records, grouping, sheet_path: Path) -> list[str]:
    r = grouping.report
    lines = [
        (
            f"Images found: {r['images']} (A: {sum(x.dataset == 'A' for x in records)}, "
            f"B: {sum(x.dataset == 'B' for x in records)})"
        ),
        f"Source groups by filename id:            {r['groups_filename']}",
        f"Source groups by pHash only:             {r['groups_phash_only']}",
        f"Source groups by images (pHash + ORB):   {r['groups_image_based']}",
        f"Final groups (images OR filename agree): {r['groups_final']}",
        (
            f"  links: {r['links_phash']} pHash, {r['links_orb']} ORB-verified "
            f"({r['orb_pairs_checked']} candidate pairs checked; strongest rejected pair had "
            f"{r['orb_inliers_rejected_max']} inliers vs. {data.ORB_MIN_INLIERS} needed)"
        ),
        "Disagreements between image-based and filename-based grouping:",
        f"  filename groups the images split apart:      {r['filename_groups_split_by_images']}",
        f"  image groups spanning several filename ids:  {r['image_groups_spanning_several_filename_ids']}",
        (
            f"Groups with conflicting labels (dropped): {r['conflicting_label_groups']} "
            f"({r['conflicting_label_images']} images)"
        ),
        f"Clean source groups: {r['clean_groups']}  per label: {r['clean_groups_per_label']}",
        f"Largest final groups (images): {r['largest_final_groups']}",
    ]

    # Sample pairs to eyeball.
    link_of = {}
    for link in grouping.links:
        link_of[(link.i, link.j)] = link
        link_of[(link.j, link.i)] = link
    pairs = []
    for group in grouping.merged_by_images:
        # A component spanning several ids must contain a direct link between two ids.
        a, b = next(
            (a, b)
            for a in group
            for b in group
            if (a, b) in link_of and records[a].filename_id != records[b].filename_id
        )
        link = link_of[(a, b)]
        pairs.append(
            (a, b, f"images merge different filename ids ({link.method} {link.score:.0f})")
        )
        if len(pairs) == 5:
            break
    # Hardest accepted copies first (fewest ORB inliers), at most one pair per group.
    shown = {grouping.group_of[a] for a, _, _ in pairs}
    orb_links = sorted((l for l in grouping.links if l.method == "orb"), key=lambda l: l.score)
    for link in orb_links:
        if grouping.group_of[link.i] not in shown and len(pairs) < 8:
            shown.add(grouping.group_of[link.i])
            pairs.append((link.i, link.j, f"re-crop/rotation copy, ORB {link.score:.0f} inliers"))
    flips = sorted(
        (l for l in grouping.links if l.method == "phash" and l.score > 0), key=lambda l: -l.score
    )
    for link in flips[:1]:
        pairs.append((link.i, link.j, f"pHash {link.score:.0f} bits (flip/rotate/recolour)"))
    for group in grouping.split_by_images[:2]:
        a = group[0]
        b = next(m for m in group if grouping.image_group_of[m] != grouping.image_group_of[a])
        pairs.append((a, b, "same filename id, images NOT matched"))
    pairs = pairs[:10]
    if pairs:
        data.sample_pair_sheet(records, pairs, sheet_path)
        lines.append(f"Sample pairs ({len(pairs)}) saved to {sheet_path}:")
        lines += [
            f"  {records[a].path.name}  <->  {records[b].path.name}   [{c}]" for a, b, c in pairs
        ]
    return lines


# ----------------------------------------------------------------------------------------
# Face crops for the chosen images (cached)
# ----------------------------------------------------------------------------------------


def face_crops(records, chosen: list[int], analyzer, data_dir: Path, fresh: bool):
    cache = data_dir / "_cache" / "face_crops.npz"
    keys = [str(records[i].path.relative_to(data_dir)) for i in chosen]
    if cache.is_file() and not fresh:
        saved = np.load(cache, allow_pickle=False)
        if list(saved["paths"]) == keys:
            log(f"Reusing cached face crops ({cache.name}).")
            return saved["crops"], saved["tone"], saved["passes"]

    log(f"Cropping faces for {len(chosen)} images (same detector + alignment as the service)...")
    crops, tones, passes = [], [], []
    for n, index in enumerate(chosen, start=1):
        image = downscale(data.read_image(records[index].path))
        face = analyzer.face_detector.detect(image)[0]
        aligned = align_face(image, face)
        crops.append(classifier_input(aligned))
        tone = measure_lighting(aligned, build_maps(aligned), image).skin_to_white
        tones.append(np.nan if tone is None else tone)
        try:  # would the live service accept this photo at all?
            analyzer.analyze(image)
            passes.append(True)
        except (ImageRejected, ValueError):
            passes.append(False)
        if n % 250 == 0:
            log(f"  {n}/{len(chosen)}")
    crops, tones, passes = np.stack(crops), np.array(tones), np.array(passes)
    np.savez(cache, paths=np.array(keys), crops=crops, tone=tones, passes=passes)
    return crops, tones, passes


# ----------------------------------------------------------------------------------------
# Training
# ----------------------------------------------------------------------------------------


def train(x_train, y_train, x_val, y_val, args, device):
    import torch
    import torchvision
    from torchvision.transforms import v2

    weights = torchvision.models.EfficientNet_B0_Weights.IMAGENET1K_V1
    model = torchvision.models.efficientnet_b0(weights=weights)
    model.classifier[1] = torch.nn.Linear(model.classifier[1].in_features, len(LABELS))
    model = model.to(device)

    # Class weighting: combination is ~3x rarer than the others.
    counts = np.bincount(y_train, minlength=len(LABELS))
    class_weights = counts.sum() / (len(LABELS) * np.maximum(counts, 1))
    log("Class weights:", {lab: round(float(w), 2) for lab, w in zip(LABELS, class_weights)})
    loss_fn = torch.nn.CrossEntropyLoss(
        weight=torch.tensor(class_weights, dtype=torch.float32, device=device), label_smoothing=0.1
    )
    optimizer = torch.optim.AdamW(
        [
            {"params": model.features.parameters(), "lr": args.lr},
            {"params": model.classifier.parameters(), "lr": args.lr * 5},
        ],
        weight_decay=1e-4,
    )
    steps_per_epoch = int(np.ceil(len(x_train) / args.batch_size))
    total_steps, warmup = args.epochs * steps_per_epoch, steps_per_epoch
    scheduler = torch.optim.lr_scheduler.LambdaLR(
        optimizer,
        lambda step: (
            (step + 1) / warmup
            if step < warmup
            else 0.5 * (1 + np.cos(np.pi * (step - warmup) / max(total_steps - warmup, 1)))
        ),
    )
    # Mild augmentation: lighting and framing vary in selfies, but strong colour changes
    # would destroy the shine/dullness cues that skin type shows up as.
    augment = v2.Compose(
        [
            v2.RandomResizedCrop(INPUT_SIZE, scale=(0.75, 1.0), ratio=(0.9, 1.1), antialias=True),
            v2.RandomHorizontalFlip(),
            v2.RandomRotation(8),
            v2.ColorJitter(brightness=0.15, contrast=0.15, saturation=0.1, hue=0.02),
        ]
    )
    mean = torch.tensor(IMAGENET_MEAN, device=device).view(1, 3, 1, 1)
    std = torch.tensor(IMAGENET_STD, device=device).view(1, 3, 1, 1)
    autocast = (
        torch.autocast("cuda", dtype=torch.bfloat16)
        if device == "cuda"
        else torch.autocast("cpu", enabled=False)
    )
    x_train_t = torch.from_numpy(x_train).permute(0, 3, 1, 2)  # uint8 NCHW
    generator = torch.Generator().manual_seed(args.seed)

    best = {"macro_f1": -1.0}
    history, stale = [], 0
    for epoch in range(1, args.epochs + 1):
        started = time.perf_counter()
        model.train()
        order = torch.randperm(len(x_train_t), generator=generator)
        total_loss = 0.0
        for start in range(0, len(order), args.batch_size):
            idx = order[start : start + args.batch_size]
            batch = torch.stack([augment(x_train_t[i]) for i in idx]).to(device).float() / 255.0
            batch = (batch - mean) / std
            target = torch.from_numpy(y_train[idx.numpy()]).to(device)
            with autocast:
                loss = loss_fn(model(batch), target)
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            optimizer.step()
            scheduler.step()
            total_loss += loss.item() * len(idx)

        val_probs = predict(model, x_val, device)
        val_pred = val_probs.argmax(1)
        val_metrics = metrics(y_val, val_pred)
        row = {
            "epoch": epoch,
            "train_loss": total_loss / len(order),
            "val_accuracy": val_metrics["accuracy"],
            "val_macro_f1": val_metrics["macro_f1"],
            "seconds": time.perf_counter() - started,
        }
        history.append(row)
        log(
            f"epoch {epoch:2d}  train loss {row['train_loss']:.3f}  val acc {row['val_accuracy']:.3f}  "
            f"val macro-F1 {row['val_macro_f1']:.3f}  ({row['seconds']:.1f} s)"
        )
        if val_metrics["macro_f1"] > best["macro_f1"]:
            best = {
                "macro_f1": val_metrics["macro_f1"],
                "epoch": epoch,
                "state": {k: v.detach().cpu().clone() for k, v in model.state_dict().items()},
            }
            stale = 0
        else:
            stale += 1
            if stale >= args.patience:
                log(f"Early stop: no val macro-F1 gain for {args.patience} epochs.")
                break
    model.load_state_dict(best["state"])
    log(f"Best epoch {best['epoch']} (val macro-F1 {best['macro_f1']:.3f}).")
    return model, best, history


def predict(model, x: np.ndarray, device: str) -> np.ndarray:
    import torch

    mean = torch.tensor(IMAGENET_MEAN, device=device).view(1, 3, 1, 1)
    std = torch.tensor(IMAGENET_STD, device=device).view(1, 3, 1, 1)
    model.eval()
    out = []
    with torch.inference_mode():
        for start in range(0, len(x), 128):
            batch = (
                torch.from_numpy(x[start : start + 128]).to(device).permute(0, 3, 1, 2).float()
                / 255.0
            )
            out.append(torch.softmax(model((batch - mean) / std).float(), dim=1).cpu().numpy())
    return np.concatenate(out)


# ----------------------------------------------------------------------------------------
# Metrics
# ----------------------------------------------------------------------------------------


def confusion(y_true, y_pred) -> np.ndarray:
    matrix = np.zeros((len(LABELS), len(LABELS)), dtype=int)
    np.add.at(matrix, (y_true, y_pred), 1)
    return matrix


def metrics(y_true, y_pred) -> dict:
    matrix = confusion(y_true, y_pred)
    support = matrix.sum(1)
    predicted = matrix.sum(0)
    tp = np.diag(matrix)
    precision = np.divide(tp, predicted, out=np.zeros(len(LABELS)), where=predicted > 0)
    recall = np.divide(tp, support, out=np.zeros(len(LABELS)), where=support > 0)
    f1 = np.divide(
        2 * precision * recall,
        precision + recall,
        out=np.zeros(len(LABELS)),
        where=(precision + recall) > 0,
    )
    present = support > 0
    return {
        "n": len(y_true),
        "accuracy": float(tp.sum() / max(len(y_true), 1)),
        "macro_f1": float(f1[present].mean()) if present.any() else 0.0,
        "balanced_accuracy": float(recall[present].mean()) if present.any() else 0.0,
        "per_class": {
            label: {"precision": float(p), "recall": float(r), "f1": float(f), "support": int(s)}
            for label, p, r, f, s in zip(LABELS, precision, recall, f1, support)
        },
        "confusion": matrix.tolist(),
    }


def bootstrap_ci(y_true, y_pred, key: str, seed: int, n: int = 2000) -> tuple[float, float]:
    rng = np.random.default_rng(seed)
    values = []
    for _ in range(n):
        sample = rng.integers(0, len(y_true), len(y_true))
        values.append(metrics(y_true[sample], y_pred[sample])[key])
    low, high = np.percentile(values, [2.5, 97.5])
    return float(low), float(high)


def markdown_report(result: dict) -> str:
    t = result["test"]
    lines = [
        "# Skin-type classifier: test results",
        "",
        f"Model `{result['version']}`, EfficientNet-B0 (ImageNet weights) fine-tuned on aligned face crops.",
        f"Trained {result['epochs_run']} epochs (best epoch {result['best_epoch']}), seed {result['seed']}.",
        "",
        "## Data",
        "",
        "| split | " + " | ".join(LABELS) + " | total |",
        "|---|" + "---|" * (len(LABELS) + 1),
    ]
    for split in ("train", "val", "test"):
        counts = result["split_counts"][split]
        lines.append(
            f"| {split} | "
            + " | ".join(str(counts.get(l, 0)) for l in LABELS)
            + f" | {sum(counts.values())} |"
        )
    lines += [
        "",
        "## Test split (never used for training or model selection)",
        "",
        f"- Accuracy: **{t['accuracy']:.3f}** (95% bootstrap CI {t['accuracy_ci'][0]:.3f}-{t['accuracy_ci'][1]:.3f})",
        f"- Macro-F1: **{t['macro_f1']:.3f}** (95% CI {t['macro_f1_ci'][0]:.3f}-{t['macro_f1_ci'][1]:.3f})",
        f"- Balanced accuracy (mean per-class recall): {t['balanced_accuracy']:.3f}",
        f"- Majority-class baseline accuracy: {result['majority_baseline']:.3f}; chance macro-F1 ~ {1 / len(LABELS):.2f}",
        "",
        "| class | precision | recall | F1 | support |",
        "|---|---|---|---|---|",
    ]
    for label in LABELS:
        c = t["per_class"][label]
        lines.append(
            f"| {label} | {c['precision']:.3f} | {c['recall']:.3f} | {c['f1']:.3f} | {c['support']} |"
        )
    lines += [
        "",
        "Confusion matrix (rows = true, columns = predicted):",
        "",
        "| | " + " | ".join(LABELS) + " |",
        "|---|" + "---|" * len(LABELS),
    ]
    for label, row in zip(LABELS, t["confusion"]):
        lines.append(f"| **{label}** | " + " | ".join(str(v) for v in row) + " |")
    lines += [
        "",
        "## Skin-tone breakdown (test split; skin luminance relative to eye whites or teeth)",
        "",
        "| group | n | accuracy | macro-F1 | " + " | ".join(f"recall {l}" for l in LABELS) + " |",
        "|---|---|---|---|" + "---|" * len(LABELS),
    ]
    for name, g in result["tone_groups"].items():
        if g["n"] == 0:
            lines.append(f"| {name} | 0 | - | - |" + " - |" * len(LABELS))
            continue
        recalls = " | ".join(
            f"{g['per_class'][l]['recall']:.2f} ({g['per_class'][l]['support']})"
            if g["per_class"][l]["support"]
            else "-"
            for l in LABELS
        )
        lines.append(
            f"| {name} | {g['n']} | {g['accuracy']:.3f} | {g['macro_f1']:.3f} | {recalls} |"
        )
    lines += [
        "",
        "Tone groups, all usable images: "
        + ", ".join(f"{k} {v}" for k, v in result["tone_groups_all"].items()),
    ]
    s = result["service_accepted_test"]
    lines += [
        "",
        (
            f"Test images the live service would accept (pass all hard quality checks): {s['n']} "
            f"-> accuracy {s['accuracy']:.3f}, macro-F1 {s['macro_f1']:.3f}"
        ),
    ]
    return "\n".join(lines) + "\n"


# ----------------------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--epochs", type=int, default=30)
    parser.add_argument("--patience", type=int, default=8)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--lr", type=float, default=2e-4)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--dedup-only", action="store_true", help="stop after grouping + split report"
    )
    parser.add_argument("--fresh", action="store_true", help="ignore cached signatures and crops")
    parser.add_argument("--allow-cpu", action="store_true")
    parser.add_argument("--data", type=Path, default=DATASETS_DIR, help="datasets folder")
    parser.add_argument("--out", type=Path, default=WEIGHTS_DIR, help="weights + report folder")
    args = parser.parse_args()
    data_dir, out_dir = args.data.resolve(), args.out.resolve()
    weights_path = out_dir / WEIGHTS_PATH.name

    import torch

    device = check_gpu(args.allow_cpu)
    seed_everything(args.seed)
    analyzer = load_models()

    records = data.discover(data_dir)
    log(
        f"Discovered {len(records)} images:",
        dict(Counter((r.dataset, r.original_split, r.label) for r in records)),
    )

    phash, embeddings, face_width, orb = compute_signatures(
        records, analyzer, device, data_dir, args.fresh
    )
    distances = data.phash_distances(phash)
    candidates = data.retrieve_candidates(embeddings, device)
    grouping = data.group_records(records, phash, distances, candidates, orb)
    log(
        "\n".join(
            report_grouping(records, grouping, data_dir / "_reports" / "dedup_sample_pairs.jpg")
        )
    )

    # Usable groups: one consistent label and at least one copy with a detectable face.
    # The representative is the copy with the largest face (most detail).
    members = defaultdict(list)
    for index, gid in enumerate(grouping.group_of):
        members[int(gid)].append(index)
    conflicting = {int(grouping.group_of[m[0]]) for m in grouping.conflicting}
    representative, no_face = {}, Counter()
    for gid, idx in members.items():
        if gid in conflicting:
            continue
        best = max(idx, key=lambda i: face_width[i])
        if face_width[best] > 0:
            representative[gid] = best
        else:
            no_face[records[idx[0]].label] += 1
    log(
        f"Groups with no detectable face in any copy (excluded): {sum(no_face.values())} {dict(no_face)}"
    )

    group_label = {gid: records[i].label for gid, i in representative.items()}
    split_of_group = data.split_groups(group_label, args.seed)
    split_of_record = {i: split_of_group[gid] for gid in representative for i in members[gid]}
    log("Leakage check (all copies of every usable group, train/val/test):")
    log(
        "\n".join(
            "  " + line
            for line in data.overlap_check(split_of_record, records, grouping, distances, orb)
        )
    )
    split_counts = {
        s: dict(Counter(group_label[g] for g, sp in split_of_group.items() if sp == s))
        for s in ("train", "val", "test")
    }
    for split, counts in split_counts.items():
        log(f"  {split:>5}: {sum(counts.values())} source images {counts}")

    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        split: sorted(
            str(records[representative[g]].path.relative_to(data_dir))
            for g, sp in split_of_group.items()
            if sp == split
        )
        for split in ("train", "val", "test")
    }
    (out_dir / "skin_type_split.json").write_text(
        json.dumps({"seed": args.seed, **manifest}, indent=1)
    )
    if args.dedup_only:
        return 0

    chosen = sorted(representative.values())
    crops, tones, passes = face_crops(records, chosen, analyzer, data_dir, args.fresh)
    position = {index: k for k, index in enumerate(chosen)}

    def arrays(split):
        idx = [
            position[representative[g]] for g, sp in sorted(split_of_group.items()) if sp == split
        ]
        y = np.array([LABELS.index(records[chosen[k]].label) for k in idx])
        return crops[idx], y, tones[idx], passes[idx]

    x_train, y_train, _, _ = arrays("train")
    x_val, y_val, _, _ = arrays("val")
    x_test, y_test, tone_values_test, pass_test = arrays("test")

    model, best, history = train(x_train, y_train, x_val, y_val, args, device)

    # The test split is touched exactly once, here.
    test_pred = predict(model, x_test, device).argmax(1)
    test = metrics(y_test, test_pred)
    test["accuracy_ci"] = bootstrap_ci(y_test, test_pred, "accuracy", args.seed)
    test["macro_f1_ci"] = bootstrap_ci(y_test, test_pred, "macro_f1", args.seed)
    tone_test = np.array([tone_group(v) for v in tone_values_test])
    tone_names = {
        "lighter": f"lighter (skin/white >= {cfg.TONE_LIGHTER_AT_LEAST})",
        "darker": f"darker (skin/white < {cfg.TONE_LIGHTER_AT_LEAST})",
        "unknown": "tone unknown (no usable eye white or teeth)",
    }
    tone_groups = {
        title: metrics(y_test[tone_test == key], test_pred[tone_test == key])
        for key, title in tone_names.items()
    }

    state = {k: v.contiguous() for k, v in model.cpu().state_dict().items()}
    digest = hashlib.sha256(b"".join(v.numpy().tobytes() for v in state.values())).hexdigest()[:8]
    version = f"effnetb0-{datetime.now(UTC):%Y%m%d}-{digest}"
    result = {
        "version": version,
        "seed": args.seed,
        "epochs_run": len(history),
        "best_epoch": best["epoch"],
        "labels": LABELS,
        "split_counts": split_counts,
        "dedup": grouping.report,
        "test": test,
        "majority_baseline": float(np.bincount(y_test).max() / len(y_test)),
        "tone_groups": tone_groups,
        "tone_groups_all": dict(Counter(tone_group(v) for v in tones)),
        "relative_skin_luminance_all": [None if np.isnan(v) else round(float(v), 3) for v in tones],
        "service_accepted_test": metrics(y_test[pass_test], test_pred[pass_test]),
        "service_accepted_all": int(passes.sum()),
        "history": history,
    }
    torch.save(
        {
            "state_dict": state,
            "labels": LABELS,
            "version": version,
            "input_size": INPUT_SIZE,
            "test_accuracy": test["accuracy"],
            "test_macro_f1": test["macro_f1"],
            "test_macro_f1_ci": list(test["macro_f1_ci"]),
        },
        weights_path,
    )
    (out_dir / "skin_type_report.json").write_text(json.dumps(result, indent=1))
    (out_dir / "skin_type_report.md").write_text(markdown_report(result), encoding="utf-8")
    log("\n" + markdown_report(result))
    log(
        f"Saved {weights_path} ({weights_path.stat().st_size / 1e6:.1f} MB) and reports in {out_dir}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
