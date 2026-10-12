# Fine-tuning the food classifier for Indian dishes (optional)

The backend ships with `nateraw/food`: a ViT-base model pretrained on ImageNet-21k and **fine-tuned on
Food-101** (101 dishes, ~89% eval accuracy). That is the project's transfer-learning component. Food-101 is
Western-heavy, so its predictions are used only as weak *hints* for Gemini.

`finetune_indian_food.py` is the next transfer-learning step: it starts from `nateraw/food`, swaps the
101-class head for your Indian classes, and fine-tunes in two phases. **It was not run during the build.**

## 1. Get a dataset

Any ImageFolder layout works:

```
ml/data/indian_food/
  aloo_gobi/ 001.jpg 002.jpg …
  biryani/   …
  chole_bhature/ …
```

A good starting point is the Kaggle **"Indian Food Images"** dataset (80 classes):

```bash
pip install kaggle   # needs ~/.kaggle/kaggle.json
kaggle datasets download -d iamsouravbanerjee/indian-food-images-dataset -p ml/data --unzip
# move/rename so the class folders sit directly under ml/data/indian_food/
```

(`ml/data/` and `ml/output/` are git-ignored.)

## 2. Train on a GPU (Colab / Kaggle)

```bash
pip install -r requirements.txt torchvision datasets accelerate
python ml/finetune_indian_food.py --data-dir ml/data/indian_food --food101-classes 20
```

* Phase 1 — encoder frozen, train the new head: 3 epochs, lr 1e-3.
* Phase 2 — unfreeze the last 4 encoder layers: 8 epochs, lr 5e-5, cosine schedule, warmup 0.1, label smoothing 0.1.
* Augmentations: RandomResizedCrop(224), horizontal flip, ColorJitter.
* `--food101-classes N` mixes in N Food-101 classes so the model doesn't forget Western dishes.

It prints validation top-1 / top-5 accuracy and saves to `ml/output/indian-food-vit/`. A T4 GPU takes
roughly 20–40 minutes for the 80-class dataset.

## 3. Point the backend at your model

Copy `ml/output/indian-food-vit/` next to the backend (or push it to the Hugging Face Hub), then set:

```bash
CLASSIFIER_MODEL_ID=ml/output/indian-food-vit     # local path, or your-hf-user/indian-food-vit
```

Restart the API. `GET /api/v1/health` should show `"classifier": "loaded"`, and scan responses will show
your model's id in `classifier.model`.
