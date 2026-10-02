"""Skin-type training data: discovery, duplicate grouping, and a leak-free split.

The two Kaggle datasets are Roboflow exports. Each source photo appears up to 7 times
(flipped, rotated, re-cropped, recoloured copies), and the same photo can appear in both
datasets and in several of their splits. Splitting naively would put copies of one photo
in train *and* test, so copies are grouped first and whole groups are assigned to a split.

Grouping (image-based):
1. pHash, compared under all 8 flips/90-degree rotations: catches exact copies, flips,
   rotations by 90 degrees, recompression, recolouring and stretching.
2. pHash alone misses re-crops (> ~15%) and small rotations (> ~10 deg): those land as far
   apart as two different people. So for every image the most similar images by a
   pretrained CNN embedding are retrieved and confirmed (or not) with ORB keypoints +
   RANSAC geometric verification. Copies share hundreds of geometrically consistent
   keypoints; different photos share a handful.
Both ignore the black padding Roboflow adds around rotated copies (pHash on the content's
bounding box, ORB keypoints only on content). A first run without that let the padding
itself match: different photos linked, and transitive links chained 760 images into one
"group".
The image-based groups are cross-checked against the source id that Roboflow kept in
the filenames. The final grouping links images if EITHER says they are copies, which
errs on the side of no leakage.
"""

import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

DATASET_FOLDERS = {"A": "Oily-Dry-Skin-Types", "B": "skin_type_classification_dataset"}
LABELS = ("combination", "dry", "normal", "oily")
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}

PHASH_MAX_BITS = 6  # of 64: same photo up to flips/rotations/recolouring
RETRIEVAL_NEIGHBOURS = 8  # CNN nearest neighbours per image sent to ORB verification
RETRIEVAL_MIN_SIMILARITY = 0.5  # cosine; below this a pair is not even checked
ORB_SIDE_PX = 400  # images are resized to this longest side for ORB
ORB_FEATURES = 600
ORB_MIN_INLIERS = 50  # geometrically consistent matches needed to call two images copies
CONTENT_MIN_LEVEL = 18  # 8-bit: anything darker in every channel counts as black padding
ORB_PADDING_MARGIN_PX = 8  # no keypoints within this distance of padding (at ORB_SIDE_PX)

_SOURCE_ID = re.compile(r"[0-9a-f]{20}")


@dataclass
class Record:
    path: Path
    dataset: str  # "A" or "B"
    original_split: str
    label: str
    filename_id: str  # source id Roboflow kept in the filename


@dataclass
class Link:
    i: int
    j: int
    method: str  # "phash", "orb" or "filename"
    score: float  # pHash bits (lower = closer) or ORB inliers (higher = closer)


@dataclass
class Grouping:
    group_of: np.ndarray  # final group id per record
    image_group_of: np.ndarray  # group id per record from the images alone (pHash + ORB)
    links: list[Link]
    report: dict
    split_by_images: list[list[int]]  # filename groups the image-based grouping splits
    merged_by_images: list[list[int]]  # image-based groups spanning several filename ids
    conflicting: list[list[int]]  # final groups whose copies carry different labels
    orb_checked: list[tuple[int, int, int]]  # (i, j, inliers) for every verified pair


# ----------------------------------------------------------------------------------------
# Discovery
# ----------------------------------------------------------------------------------------


def find_dataset_roots(datasets_dir: Path) -> dict[str, Path]:
    roots = {}
    for key, folder in DATASET_FOLDERS.items():
        matches = sorted(
            p
            for p in datasets_dir.rglob(folder)
            if p.is_dir() and len(p.relative_to(datasets_dir).parts) <= 3
        )
        if not matches:
            raise FileNotFoundError(
                f"Couldn't find a folder named {folder!r} under {datasets_dir}. Unzip both "
                "Kaggle datasets there (see README.md, 'Skin-type classifier')."
            )
        roots[key] = matches[0]
    return roots


def filename_id(name: str) -> str:
    stem = name.split(".rf.")[0].lower()
    match = _SOURCE_ID.search(stem)
    return match.group(0) if match else stem.replace("-copy", "")


def discover(datasets_dir: Path) -> list[Record]:
    records = []
    for key, root in find_dataset_roots(datasets_dir).items():
        for split_dir in sorted(p for p in root.iterdir() if p.is_dir()):
            for label_dir in sorted(p for p in split_dir.iterdir() if p.is_dir()):
                label = label_dir.name.lower()
                if label not in LABELS:
                    raise ValueError(f"unexpected label folder {label_dir}")
                for path in sorted(label_dir.iterdir()):
                    if path.suffix.lower() in IMAGE_SUFFIXES:
                        records.append(
                            Record(path, key, split_dir.name, label, filename_id(path.name))
                        )
    return records


def read_image(path: Path) -> np.ndarray | None:
    """BGR uint8, or None if unreadable. np.fromfile copes with any Windows path."""
    return cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)


# ----------------------------------------------------------------------------------------
# Signatures
# ----------------------------------------------------------------------------------------


def dihedral(image: np.ndarray) -> list[np.ndarray]:
    """The 8 flips/90-degree rotations of an image."""
    out = []
    for k in range(4):
        rotated = np.rot90(image, k)
        out += [rotated, rotated[:, ::-1]]
    return [np.ascontiguousarray(x) for x in out]


def content_mask(image: np.ndarray) -> np.ndarray:
    """uint8 mask of image content, i.e. not the near-black padding around rotated copies."""
    mask = (image.max(axis=2) > CONTENT_MIN_LEVEL).astype(np.uint8)
    return cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))


def content_crop(image: np.ndarray) -> np.ndarray:
    """The image cropped to its content, with any padding left inside the crop (the black
    corner triangles of a rotated copy) filled with the content's median colour. Without
    the fill, two different photos rotated by a similar angle share the same triangles
    and pHash sees them as near-identical."""
    mask = content_mask(image)
    ys, xs = np.nonzero(mask)
    if len(xs) < 0.05 * image.shape[0] * image.shape[1]:  # (almost) all dark: keep as is
        return image
    box = (slice(ys.min(), ys.max() + 1), slice(xs.min(), xs.max() + 1))
    crop, inside = image[box].copy(), mask[box].astype(bool)
    crop[~inside] = np.median(crop[inside], axis=0).astype(np.uint8)
    return np.ascontiguousarray(crop)


_phash = cv2.img_hash.PHash_create()


def phash_dihedral(image: np.ndarray) -> np.ndarray:
    """(8,) uint64 pHashes, one per flip/rotation."""
    return np.array(
        [int.from_bytes(_phash.compute(x).tobytes(), "big") for x in dihedral(image)],
        dtype=np.uint64,
    )


_orb = cv2.ORB_create(nfeatures=ORB_FEATURES)


def orb_features(image: np.ndarray) -> list[tuple[np.ndarray, np.ndarray] | None]:
    """ORB (points, descriptors) for the image and its mirror image. ORB is rotation-
    invariant but not mirror-invariant, hence both."""
    scale = ORB_SIDE_PX / max(image.shape[:2])
    small = cv2.resize(image, None, fx=scale, fy=scale)
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    # Keypoints only on content and away from its border with any padding: padding edges
    # and corners otherwise "match" between unrelated rotated copies.
    margin = 2 * ORB_PADDING_MARGIN_PX + 1
    mask = cv2.erode(content_mask(small), np.ones((margin, margin), np.uint8))
    out = []
    for view, view_mask in (
        (gray, mask),
        (np.ascontiguousarray(gray[:, ::-1]), np.ascontiguousarray(mask[:, ::-1])),
    ):
        keypoints, descriptors = _orb.detectAndCompute(view, view_mask)
        if descriptors is None or len(keypoints) < 8:
            out.append(None)
        else:
            out.append((np.float32([k.pt for k in keypoints]), descriptors))
    return out


_matcher = cv2.BFMatcher(cv2.NORM_HAMMING)


def orb_inliers(a, b_views) -> int:
    """Most RANSAC-consistent keypoint matches between image a and image b (or b's mirror)."""
    if a is None:
        return 0
    best = 0
    for b in b_views:
        if b is None:
            continue
        pairs = _matcher.knnMatch(a[1], b[1], k=2)
        good = [p[0] for p in pairs if len(p) == 2 and p[0].distance < 0.75 * p[1].distance]
        if len(good) < 8:
            continue
        src = a[0][[g.queryIdx for g in good]]
        dst = b[0][[g.trainIdx for g in good]]
        # Full affine: re-crops, rotations, resizing and Roboflow's non-uniform stretch.
        _, inliers = cv2.estimateAffine2D(src, dst, method=cv2.RANSAC, ransacReprojThreshold=5.0)
        if inliers is not None:
            best = max(best, int(inliers.sum()))
    return best


def cnn_embeddings(images: list[np.ndarray], device: str) -> np.ndarray:
    """(N, 4, D) L2-normalised ImageNet EfficientNet-B0 features for each image at the 4
    90-degree rotations, each averaged with its mirror image. Used only to *retrieve*
    candidate copies; ORB makes the decision."""
    import torch
    import torchvision

    weights = torchvision.models.EfficientNet_B0_Weights.IMAGENET1K_V1
    model = torchvision.models.efficientnet_b0(weights=weights)
    model.classifier = torch.nn.Identity()
    model = model.to(device).eval()
    mean = torch.tensor([0.485, 0.456, 0.406], device=device).view(1, 3, 1, 1)
    std = torch.tensor([0.229, 0.224, 0.225], device=device).view(1, 3, 1, 1)

    out = []
    with torch.inference_mode():
        for start in range(0, len(images), 64):
            batch = np.stack([_square(x, 224) for x in images[start : start + 64]])
            x = torch.from_numpy(batch).to(device).permute(0, 3, 1, 2).float() / 255.0
            x = (x - mean) / std
            per_rotation = []
            for k in range(4):
                r = torch.rot90(x, k, dims=(2, 3))
                f = model(r) + model(torch.flip(r, dims=(3,)))
                per_rotation.append(torch.nn.functional.normalize(f, dim=1))
            out.append(torch.stack(per_rotation, dim=1).cpu().numpy().astype(np.float16))
    return np.concatenate(out)


def _square(image: np.ndarray, size: int) -> np.ndarray:
    """Letterbox to a square RGB image of `size` px."""
    h, w = image.shape[:2]
    side = max(h, w)
    canvas = np.zeros((side, side, 3), np.uint8)
    canvas[(side - h) // 2 : (side - h) // 2 + h, (side - w) // 2 : (side - w) // 2 + w] = image
    return cv2.cvtColor(
        cv2.resize(canvas, (size, size), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2RGB
    )


# ----------------------------------------------------------------------------------------
# Grouping
# ----------------------------------------------------------------------------------------


def phash_distances(hashes: np.ndarray) -> np.ndarray:
    """(N, N) uint8: min Hamming distance between image i and any flip/rotation of j."""
    n = len(hashes)
    out = np.empty((n, n), dtype=np.uint8)
    for start in range(0, n, 128):
        xor = hashes[start : start + 128, :1][:, None, :] ^ hashes[None, :, :]
        out[start : start + 128] = np.bitwise_count(xor).min(axis=2)
    return np.minimum(out, out.T)


def retrieve_candidates(embeddings: np.ndarray, device: str) -> list[tuple[int, int, float]]:
    """(i, j, cosine) for each image's RETRIEVAL_NEIGHBOURS most similar images."""
    import torch

    e = torch.from_numpy(embeddings.astype(np.float32)).to(device)  # (N, 4, D)
    n = e.shape[0]
    flat = e.reshape(n * 4, -1)
    pairs = set()
    out = []
    for start in range(0, n, 256):
        sims = (e[start : start + 256, 0] @ flat.T).reshape(-1, n, 4).amax(dim=2)
        rows = torch.arange(start, min(start + 256, n), device=device)
        sims[rows - start, rows] = -1.0  # not yourself
        values, indices = sims.topk(RETRIEVAL_NEIGHBOURS, dim=1)
        for i, (vals, idxs) in enumerate(zip(values.tolist(), indices.tolist()), start=start):
            for value, j in zip(vals, idxs):
                key = (min(i, j), max(i, j))
                if value >= RETRIEVAL_MIN_SIMILARITY and key not in pairs:
                    pairs.add(key)
                    out.append((key[0], key[1], value))
    return out


class _UnionFind:
    def __init__(self, n: int):
        self.parent = list(range(n))

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        self.parent[self.find(a)] = self.find(b)

    def labels(self) -> np.ndarray:
        roots = [self.find(i) for i in range(len(self.parent))]
        _, ids = np.unique(roots, return_inverse=True)
        return ids


def components(n: int, links: list[Link]) -> np.ndarray:
    uf = _UnionFind(n)
    for link in links:
        uf.union(link.i, link.j)
    return uf.labels()


def group_records(
    records: list[Record],
    hashes: np.ndarray,
    phash_dist: np.ndarray,
    candidates: list[tuple[int, int, float]],
    orb: list,
) -> Grouping:
    n = len(records)
    links = [
        Link(int(i), int(j), "phash", float(phash_dist[i, j]))
        for i, j in zip(*np.nonzero(np.triu(phash_dist <= PHASH_MAX_BITS, k=1)))
    ]
    linked = {(l.i, l.j) for l in links}
    orb_checked = []
    for i, j, _ in candidates:
        if (i, j) in linked:
            continue
        inliers = orb_inliers(orb[i][0], orb[j])
        orb_checked.append((i, j, inliers))
        if inliers >= ORB_MIN_INLIERS:
            links.append(Link(i, j, "orb", float(inliers)))

    by_name = defaultdict(list)
    for index, record in enumerate(records):
        by_name[record.filename_id].append(index)
    name_links = [
        Link(members[0], other, "filename", 0.0)
        for members in by_name.values()
        for other in members[1:]
    ]

    phash_groups = components(n, [l for l in links if l.method == "phash"])
    image_groups = components(n, links)
    name_groups = components(n, name_links)
    final = components(n, links + name_links)

    # Where the image-based and filename-based groupings disagree.
    split_by_images = []  # filename groups the image-based grouping splits apart
    for members in by_name.values():
        if len({image_groups[m] for m in members}) > 1:
            split_by_images.append(members)
    merged_by_images = []  # image-based groups spanning several filename ids
    image_members = defaultdict(list)
    for index, gid in enumerate(image_groups):
        image_members[gid].append(index)
    for members in image_members.values():
        if len({records[m].filename_id for m in members}) > 1:
            merged_by_images.append(members)

    final_members = defaultdict(list)
    for index, gid in enumerate(final):
        final_members[gid].append(index)
    conflicting = [m for m in final_members.values() if len({records[i].label for i in m}) > 1]
    clean = [m for m in final_members.values() if len({records[i].label for i in m}) == 1]

    report = {
        "images": n,
        "groups_filename": int(name_groups.max() + 1),
        "groups_phash_only": int(phash_groups.max() + 1),
        "groups_image_based": int(image_groups.max() + 1),
        "groups_final": len(final_members),
        "links_phash": sum(l.method == "phash" for l in links),
        "links_orb": sum(l.method == "orb" for l in links),
        "orb_pairs_checked": len(orb_checked),
        "orb_inliers_rejected_max": max(
            (x for *_, x in orb_checked if x < ORB_MIN_INLIERS), default=0
        ),
        "filename_groups_split_by_images": len(split_by_images),
        "image_groups_spanning_several_filename_ids": len(merged_by_images),
        "conflicting_label_groups": len(conflicting),
        "conflicting_label_images": sum(len(m) for m in conflicting),
        "clean_groups": len(clean),
        "largest_final_groups": sorted((len(m) for m in final_members.values()), reverse=True)[:5],
        "clean_groups_per_label": dict(sorted(Counter(records[m[0]].label for m in clean).items())),
    }
    return Grouping(
        final,
        image_groups,
        links,
        report,
        split_by_images,
        merged_by_images,
        conflicting,
        orb_checked,
    )


# ----------------------------------------------------------------------------------------
# Split
# ----------------------------------------------------------------------------------------


def split_groups(
    group_labels: dict[int, str], seed: int, fractions=(0.70, 0.15, 0.15)
) -> dict[int, str]:
    """Stratified by label, at the level of whole duplicate groups."""
    rng = np.random.default_rng(seed)
    assignment = {}
    for label in LABELS:
        gids = sorted(g for g, lab in group_labels.items() if lab == label)
        rng.shuffle(gids)
        n_val = round(fractions[1] * len(gids))
        n_test = round(fractions[2] * len(gids))
        for k, gid in enumerate(gids):
            assignment[gid] = "val" if k < n_val else "test" if k < n_val + n_test else "train"
    return assignment


AUDIT_MAX_BITS = 12  # cross-split pairs this close in pHash are also checked with ORB


def overlap_check(
    split_of_record: dict[int, str],
    records: list[Record],
    grouping: Grouping,
    phash_dist: np.ndarray,
    orb: list,
) -> list[str]:
    """Human-readable proof that no source image is shared between splits.

    Beyond shared groups and filename ids, every cross-split pair within AUDIT_MAX_BITS
    of pHash (a looser net than the linking threshold) is checked with ORB; a missed
    copy would show up as a pair at or above ORB_MIN_INLIERS."""
    lines = []
    by_split = defaultdict(list)
    for index, split in split_of_record.items():
        by_split[split].append(index)
    names = ("train", "val", "test")
    for a_pos, a in enumerate(names):
        for b in names[a_pos + 1 :]:
            groups = {grouping.group_of[i] for i in by_split[a]} & {
                grouping.group_of[i] for i in by_split[b]
            }
            ids = {records[i].filename_id for i in by_split[a]} & {
                records[i].filename_id for i in by_split[b]
            }
            block = phash_dist[np.ix_(by_split[a], by_split[b])]
            near = int((block <= PHASH_MAX_BITS).sum())
            closest = f"{int(block.min())} bits" if block.size else "n/a"
            audited = [
                orb_inliers(orb[by_split[a][x]][0], orb[by_split[b][y]])
                for x, y in zip(*np.nonzero(block <= AUDIT_MAX_BITS))
            ]
            lines.append(
                f"{a:>5} vs {b:<5}  shared groups: {len(groups)}   shared filename ids: "
                f"{len(ids)}   pHash near-duplicate pairs (<= {PHASH_MAX_BITS} bits): {near}   "
                f"closest pair: {closest}   pairs within {AUDIT_MAX_BITS} bits ORB-checked: "
                f"{len(audited)}, max inliers {max(audited, default=0)} "
                f"(copy >= {ORB_MIN_INLIERS})"
            )
    return lines


def sample_pair_sheet(records: list[Record], pairs: list[tuple[int, int, str]], path: Path) -> None:
    """Contact sheet of image pairs with captions, for eyeballing merged groups."""
    rows = []
    for i, j, caption in pairs:
        tiles = []
        for index in (i, j):
            image = read_image(records[index].path)
            tile = cv2.resize(_square(image, 220)[:, :, ::-1], (220, 220))
            text = (
                f"{records[index].dataset}/{records[index].label}/{records[index].filename_id[:8]}"
            )
            cv2.putText(
                tile, text, (4, 214), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 0, 0), 3, cv2.LINE_AA
            )
            cv2.putText(
                tile,
                text,
                (4, 214),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.42,
                (255, 255, 255),
                1,
                cv2.LINE_AA,
            )
            tiles.append(tile)
        row = np.hstack([tiles[0], np.full((220, 8, 3), 255, np.uint8), tiles[1]])
        bar = np.full((24, row.shape[1], 3), 255, np.uint8)
        cv2.putText(
            bar, caption, (4, 17), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 1, cv2.LINE_AA
        )
        rows.append(np.vstack([bar, row, np.full((10, row.shape[1], 3), 255, np.uint8)]))
    columns = [np.vstack(rows[k::2]) for k in range(2) if rows[k::2]]
    height = max(c.shape[0] for c in columns)
    sheet = np.hstack(
        [
            np.vstack([c, np.full((height - c.shape[0], c.shape[1], 3), 255, np.uint8)])
            for c in columns
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), sheet, [cv2.IMWRITE_JPEG_QUALITY, 90])
