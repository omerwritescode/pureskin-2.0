"""Control experiment: the same model and training, but on the uploaders' own
train/valid/test folders (all copies, no deduplication).

This is what a naive use of the two Kaggle datasets would report. Comparing it with the
leak-free result from train_skin_type.py shows how much apparent accuracy comes from
copies of a photo sitting in both train and test. Prints results only; saves nothing.

Run from backend/ (GPU build of PyTorch, datasets unzipped):
    python -m app.services.image_analysis.naive_split_control
"""

import argparse
import sys
from collections import Counter

import numpy as np

from . import skin_type_data as data
from . import train_skin_type as t
from .analyzer import load_models
from .face import align_face
from .skin_type import classifier_input


def main() -> int:
    device = t.check_gpu(allow_cpu=False)
    t.seed_everything(42)
    analyzer = load_models()
    records = data.discover(t.DATASETS_DIR.resolve())

    train_ids = {r.filename_id for r in records if r.original_split == "train"}
    test = [r for r in records if r.original_split == "test"]
    leaked = sum(r.filename_id in train_ids for r in test)
    print(
        f"Uploaders' test folders: {len(test)} images, {leaked} ({leaked / len(test):.0%}) "
        "with a same-filename-id copy in the train folders (a lower bound)."
    )

    crops, labels, splits = [], [], []
    for record in records:
        image = t.downscale(data.read_image(record.path))
        faces = analyzer.face_detector.detect(image)
        if faces:
            crops.append(classifier_input(align_face(image, faces[0])))
            labels.append(t.LABELS.index(record.label))
            splits.append(record.original_split)
    crops, labels, splits = np.stack(crops), np.array(labels), np.array(splits)
    print("Images with a detectable face per folder:", dict(Counter(splits.tolist())))

    args = argparse.Namespace(epochs=30, patience=8, batch_size=32, lr=2e-4, seed=42)
    train, valid, test_mask = (splits == s for s in ("train", "valid", "test"))
    model, _, _ = t.train(crops[train], labels[train], crops[valid], labels[valid], args, device)
    predicted = t.predict(model, crops[test_mask], device).argmax(1)
    result = t.metrics(labels[test_mask], predicted)
    print(
        f"Naive-split test: n={result['n']}  accuracy {result['accuracy']:.3f}  "
        f"macro-F1 {result['macro_f1']:.3f}  balanced accuracy {result['balanced_accuracy']:.3f}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
