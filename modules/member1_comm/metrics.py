"""Confusion-count metrics; absent denominators remain unevaluated."""
from collections import Counter

ATTACK_LABELS = ('metasploit SYN flood', 'nmap SYN flood', 'nmap discovery', 'ros2 reconnaissance', 'ros2 node crashing', 'ros2 reflection')
LABELS = ('observe',) + ATTACK_LABELS


def ratio(a, b):
    return a / b if b else None


def evaluate(labels, predictions, scores=None):
    labels, predictions = list(labels), list(predictions)
    if len(labels) != len(predictions) or not labels:
        raise ValueError('nonempty matching labels/predictions required')
    if any(label not in LABELS for label in labels) or any(type(p) is not int or p not in (0, 1) for p in predictions):
        raise ValueError('invalid label/prediction')
    y = [int(label != 'observe') for label in labels]
    tp = sum(t == p == 1 for t, p in zip(y, predictions))
    tn = sum(t == p == 0 for t, p in zip(y, predictions))
    fp = sum(t == 0 and p == 1 for t, p in zip(y, predictions))
    fn = sum(t == 1 and p == 0 for t, p in zip(y, predictions))
    recall, specificity = ratio(tp, tp + fn), ratio(tn, tn + fp)
    balanced = (recall + specificity) / 2 if recall is not None and specificity is not None else None
    per_class = {}
    for label in ATTACK_LABELS:
        indices = [i for i, item in enumerate(labels) if item == label]
        per_class[label] = {'count': len(indices), 'recall': ratio(sum(predictions[i] for i in indices), len(indices)), 'status': 'EVALUATED' if indices else 'NOT_EVALUATED'}
    recalls = [item['recall'] for item in per_class.values() if item['recall'] is not None]
    counts = Counter(labels)
    result = {'confusion': {'tp': tp, 'tn': tn, 'fp': fp, 'fn': fn}, 'precision': ratio(tp, tp + fp),
              'recall': recall, 'specificity': specificity, 'fpr': ratio(fp, fp + tn), 'f1': ratio(2 * tp, 2 * tp + fp + fn),
              'balanced_accuracy': balanced, 'binary_macro_recall': balanced, 'macro_attack_detection_recall': ratio(sum(recalls), len(recalls)),
              'class_counts': dict(counts), 'class_proportions': {k:v/len(labels) for k,v in counts.items()}, 'attack_class_recall': per_class, 'pr_auc': None}
    if scores is not None and len(set(y)) == 2:
        from sklearn.metrics import average_precision_score
        result['pr_auc'] = float(average_precision_score(y, scores))
        result['pr_auc_definition'] = 'average_precision (stepwise area), not trapezoidal PR area'
    return result
