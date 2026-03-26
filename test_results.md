# AgentGuard Cross-Validation Detailed Report

## Overview
This report presents per-fold performance including:
- Fold split information
- Best validation metrics during training
- Final test results

---

## 📂 Fold 1
Dataset sizes: train=6560, val=3108, test=3130
### Fold Information
Train: ['agent-3', 'agent-8', 'agent-11', 'agent-18', 'agent-4', 'agent-12', 'agent-19', 'agent-5', 'agent-13', 'agent-20']
Val:   ['agent-2', 'agent-7', 'agent-10', 'agent-15', 'agent-17']
Test:  ['agent-1', 'agent-6', 'agent-9', 'agent-14', 'agent-16']

### Best Validation Metrics
- AUROC: 0.04078953789098717
- AUPRC: 0.02322548210704336
- F1: 0.0852378011117974
- Precision: 0.044516129032258066
- Recall: 1.0

### Test Results:
  Loss:  10.6262 (R=0.0734 C=3.2005 T=73.5225)
  AUROC:     0.0437
  AUPRC:     0.0243
  F1:        0.0888
  Precision: 0.0465
  Recall:    1.0000
  Samples: 3130 (anomalous=145, normal=2985)

---

## 📂 Fold 2

### Fold Information
Train: ['agent-1', 'agent-6', 'agent-9', 'agent-14', 'agent-16', 'agent-4', 'agent-12', 'agent-19', 'agent-5', 'agent-13', 'agent-20']
Val:   ['agent-3', 'agent-8', 'agent-11', 'agent-18']
Test:  ['agent-2', 'agent-7', 'agent-10', 'agent-15', 'agent-17']

### Best Validation Metrics
- AUROC: 0.9837006566786979
- AUPRC: 0.6183300847203472
- F1: 0.7074235807860262
- Precision: 0.7570093457943925
- Recall: 0.6639344262295082

### Test Results
Loss:  7.1091 (R=0.2861 C=3.1857 T=36.3720)
AUROC:     0.9776
AUPRC:     0.4854
F1:        0.6237
Precision: 0.6170
Recall:    0.6304
Samples: 3108 (anomalous=138, normal=2970)

---

## 📂 Fold 3

### Fold Information
Train: ['agent-1', 'agent-6', 'agent-9', 'agent-14', 'agent-16', 'agent-2', 'agent-7', 'agent-10', 'agent-15', 'agent-17', 'agent-5', 'agent-13', 'agent-20']
Val:   ['agent-4', 'agent-12', 'agent-19']
Test:  ['agent-3', 'agent-8', 'agent-11', 'agent-18']

### Best Validation Metrics
- AUROC: 0.018953646829109556
- AUPRC: 0.027148049594387748
- F1: 0.09956917185256103
- Precision: 0.05239294710327456
- Recall: 1.0

### Test Results
Loss:  9.2683 (R=0.0619 C=3.0489 T=61.5751)
AUROC:     0.0187
AUPRC:     0.0248
F1:        0.0914
Precision: 0.0479
Recall:    1.0000
Samples: 2561 (anomalous=122, normal=2439)

---

## 📂 Fold 4

### Fold Information
Train: ['agent-1', 'agent-6', 'agent-9', 'agent-14', 'agent-16', 'agent-2', 'agent-7', 'agent-10', 'agent-15', 'agent-17', 'agent-3', 'agent-8', 'agent-11', 'agent-18']
Val:   ['agent-5', 'agent-13', 'agent-20']
Test:  ['agent-4', 'agent-12', 'agent-19']

### Best Validation Metrics
- AUROC: 0.9988309716599191
- AUPRC: 0.9716202349328483
- F1: 0.958139534883721
- Precision: 0.9279279279279279
- Recall: 0.9903846153846154

### Test Results
Loss:  14.0354 (R=0.0450 C=3.0960 T=108.9437)
AUROC:     0.9911
AUPRC:     0.9262
F1:        0.9099
Precision: 0.8559
Recall:    0.9712
Samples: 1995 (anomalous=104, normal=1891)

---

## 📂 Fold 5

### Fold Information
Train: ['agent-2', 'agent-7', 'agent-10', 'agent-15', 'agent-17', 'agent-3', 'agent-8', 'agent-11', 'agent-18', 'agent-4', 'agent-12', 'agent-19']
Val:   ['agent-1', 'agent-6', 'agent-9', 'agent-14', 'agent-16']
Test:  ['agent-5', 'agent-13', 'agent-20']

### Best Validation Metrics
- AUROC: 0.9849407959336914
- AUPRC: 0.9121663020430342
- F1: 0.9013157894736842
- Precision: 0.8616352201257862
- Recall: 0.9448275862068966

### Test Results
Loss:  18.8922 (R=0.0312 C=3.2212 T=156.3979)
AUROC:     0.9960
AUPRC:     0.9699
F1:        0.9245
Precision: 0.9074
Recall:    0.9423
Samples: 2004 (anomalous=104, normal=1900)

---

## 📊 Summary Table
| Fold | AUROC  | AUPRC  | F1     | Precision | Recall |
|------|--------|--------|--------|-----------|--------|
| 1    | 0.0437 | 0.0243 | 0.0888 | 0.0465    | 1.0000 |
| 2    | 0.9776 | 0.4854 | 0.6237 | 0.6170    | 0.6304 |
| 3    | 0.0187 | 0.0248 | 0.0914 | 0.0479    | 1.0000 |
| 4    | 0.9911 | 0.9262 | 0.9099 | 0.8559    | 0.9712 |
| 5    | 0.9960 | 0.9699 | 0.9245 | 0.9074    | 0.9423 |

---

## 🧠 Notes

---