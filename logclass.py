import argparse
import os
from sklearn.model_selection import StratifiedKFold
from .utils import (
    save_params,
    load_params,
    file_handling,
    extract_features,
    TestingParameters,
)
from .preprocess import registry as preprocess_registry
from .preprocess.utils import load_logs
from .feature_engineering.utils import (
    binary_train_gtruth,
    multi_features,
)
from tqdm import tqdm
from uuid import uuid4
from .models import binary_registry as binary_classifier_registry
from .models import multi_registry as multi_classifier_registry
from .reporting import bb_registry as black_box_report_registry
from .reporting import wb_registry as white_box_report_registry


def init_flags():
    """Init command line flags used for configuration."""

    parser = argparse.ArgumentParser(
        description="Runs binary classification with "
                    + "PULearning to detect anomalous logs.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--raw_logs",
        metavar="raw_logs",
        type=str,
        nargs=1,
        default=["./LogClass/data/rawlog.txt"],
        help="input logs file path",
    )
    base_dir_default = os.path.join(
        os.path.dirname(os.path.realpath(__file__)), "outputs"
    )
    parser.add_argument(
        "--base_dir",
        metavar="base_dir",
        type=str,
        nargs=1,
        default=[base_dir_default],
        help="base output directory for pipeline output files",
    )
    parser.add_argument(
        "--logs",
        metavar="logs",
        type=str,
        nargs=1,
        default=[os.path.join(base_dir_default, "logs_without_paras.txt")],
        help="input logs file path",
    )
    parser.add_argument(
        "--logs_type",
        metavar="logs_type",
        type=str,
        nargs=1,
        default=["original"],
        choices=["original", "bgl"],
        help="Input type of logs.",
    )
    parser.add_argument(
        "--kfold",
        metavar="kfold",
        type=int,
        nargs=1,
        default=[3],
        help="kfold crossvalidation",
    )
    parser.add_argument(
        "--healthy_label",
        type=str,
        nargs=1,
        default=["unlabeled"],
        help="the labels of unlabeled logs",
    )
    parser.add_argument(
        "--features",
        metavar="features",
        type=str,
        nargs='+',
        default=["tfilf"],
        choices=["tfidf", "tfilf", "length"],
        help="Features to be extracted from the logs messages.",
    )
    parser.add_argument(
        "--report",
        metavar="report",
        type=str,
        nargs='+',
        default=["confusion_matrix"],
        choices=["confusion_matrix", "accuracy", "multi_class_acc", "top_k_svm"],
        help="Reports to be generated from the model and its predictions.",
    )
    parser.add_argument(
        "--binary_classifier",
        metavar="binary_classifier",
        type=str,
        nargs=1,
        default=["pu_learning"],
        choices=["pu_learning", "regular"],
        help="Binary classifier to be used as anomaly detector.",
    )
    parser.add_argument(
        "--multi_classifier",
        metavar="multi_classifier",
        type=str,
        nargs=1,
        default=["svm"],
        choices=["svm"],
        help="Multi-clas classifier to classify anomalies.",
    )
    parser.add_argument(
        "--train",
        action="store_true",
        default=False,
        help="If set, logclass will train on the given data. Otherwise"
             + "it will run inference on it.",
    )
    parser.add_argument(
        "--preprocess",
        action="store_true",
        default=False,
        help="If set, the raw logs parameters will be preprocessed and a "
             + "new file created with the preprocessed logs.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        default=False,
        help="force training overwriting previous output.",
    )

    return parser.parse_args()


def parse_args(args):
    """Parse provided args for runtime configuration."""
    params = {
        "logs": args.logs[0],
        "raw_logs": args.raw_logs[0],
        "kfold": args.kfold[0],
        "healthy_label": args.healthy_label[0],
        "report": args.report,
        "train": args.train,
        "preprocess": args.preprocess,
        "force": args.force,
        "base_dir": args.base_dir[0],
        "logs_type": args.logs_type[0],
        "features": args.features,
        "binary_classifier": args.binary_classifier[0],
        "multi_classifier": args.multi_classifier[0],
    }
    return params


def print_params(params):
    print("{:-^80}".format("params"))
    print("Beginning binary classification "
          + "using the following configuration:\n")
    for param, value in params.items():
        print("\t{:>13}: {}".format(param, value))
    print()
    print("-" * 80)


# TODO: to be put in a separate module as there is modules for
# preprocessing and also feature engineering
def inference(params, x_data, y_data, target_names):
    # Inference
    # Feature engineering
    x_test, vocabulary = extract_features(x_data, params)
    # Binary training features
    y_test = binary_train_gtruth(y_data)
    # Binary PU estimator with RF
    # Load Trained PU Estimator
    binary_clf_getter =\
        binary_classifier_registry.get_binary_model(
            params['binary_classifier'])
    binary_clf = binary_clf_getter(params)
    binary_clf.load()
    # Anomaly detection
    y_pred_pu = binary_clf.predict(x_test)
    get_accuracy = black_box_report_registry.get_bb_report('acc')
    binary_acc = get_accuracy(y_test, y_pred_pu)
    # MultiClass remove healthy logs
    x_infer_multi, y_infer_multi = multi_features(x_test, y_data)
    # Load MultiClass
    multi_classifier_getter =\
        multi_classifier_registry.get_multi_model(params['multi_classifier'])
    multi_classifier = multi_classifier_getter(params)
    multi_classifier.load()
    # Anomaly Classification
    pred = multi_classifier.predict(x_infer_multi)
    get_multi_acc = black_box_report_registry.get_bb_report('multi_acc')
    score = get_multi_acc(y_infer_multi, pred)

    print(binary_acc, score)
    for report in params['report']:
        try:
            get_bb_report = black_box_report_registry.get_bb_report(report)
            result = get_bb_report(y_test, y_pred_pu)
        except Exception:
            pass
        else:
            print(f'Binary classification {report} report:')
            print(result)

        try:
            get_bb_report = black_box_report_registry.get_bb_report(report)
            result = get_bb_report(y_infer_multi, pred)
        except Exception:
            pass
        else:
            print(f'Multi classification {report} report:')
            print(result)

        try:
            get_wb_report = white_box_report_registry.get_wb_report(report)
            result =\
                get_wb_report(params, binary_clf.model, vocabulary,
                              target_names=target_names, top_features=5)
        except Exception:
            pass
        else:
            print(f'Multi classification {report} report:')
            print(result)


def train(params, x_data, y_data, target_names):
    # KFold Cross Validation
    kfold = StratifiedKFold(n_splits=params['kfold']).split(x_data, y_data)
    best_pu_fs = 0.
    best_multi = 0.
    for train_index, test_index in tqdm(kfold):
        params['experiment_id'] = str(uuid4().time_low)
        print(f"\nExperiment ID: {params['experiment_id']}")
        x_train, x_test = x_data[train_index], x_data[test_index]
        y_train, y_test = y_data[train_index], y_data[test_index]
        x_train, vocabulary = extract_features(x_train, params)
        with TestingParameters(params):
            x_test, _ = extract_features(x_test, params)
        # Binary training features
        y_test_pu = binary_train_gtruth(y_test)
        y_train_pu = binary_train_gtruth(y_train)
        # Binary PULearning with RF
        binary_clf_getter =\
            binary_classifier_registry.get_binary_model(
                params['binary_classifier'])
        binary_clf = binary_clf_getter(params)
        binary_clf.fit(x_train, y_train_pu)
        y_pred_pu = binary_clf.predict(x_test)
        get_accuracy = black_box_report_registry.get_bb_report('acc')
        binary_acc = get_accuracy(y_test_pu, y_pred_pu)
        # Multi-class training features
        x_train_multi, y_train_multi =\
            multi_features(x_train, y_train)
        x_test_multi, y_test_multi = multi_features(x_test, y_test)
        # MultiClass
        multi_classifier_getter =\
            multi_classifier_registry.get_multi_model(params['multi_classifier'])
        multi_classifier = multi_classifier_getter(params)
        multi_classifier.fit(x_train_multi, y_train_multi)
        pred = multi_classifier.predict(x_test_multi)
        get_multi_acc = black_box_report_registry.get_bb_report('multi_acc')
        score = get_multi_acc(y_test_multi, pred)
        better_results = (
            binary_acc > best_pu_fs
            or (binary_acc == best_pu_fs and score > best_multi)
        )

        if better_results:
            if binary_acc > best_pu_fs:
                best_pu_fs = binary_acc
            save_params(params)
            if score > best_multi:
                best_multi = score
            print(binary_acc, score)

        # TryCatch are necessary since I'm trying to consider all 
        # reports the same when they are not 
        for report in params['report']:
            try:
                get_bb_report = black_box_report_registry.get_bb_report(report)
                result = get_bb_report(y_test_pu, y_pred_pu)
            except Exception:
                pass
            else:
                print(f'Binary classification {report} report:')
                print(result)

            try:
                get_bb_report = black_box_report_registry.get_bb_report(report)
                result = get_bb_report(y_test_multi, pred)
            except Exception:
                pass
            else:
                print(f'Multi classification {report} report:')
                print(result)

            try:
                get_wb_report = white_box_report_registry.get_wb_report(report)
                result =\
                    get_wb_report(params, binary_clf.model, vocabulary,
                                  target_names=target_names, top_features=5)
            except Exception:
                pass
            else:
                print(f'Multi classification {report} report:')
                print(result)


def main():
    # Init params
    params = parse_args(init_flags())
    if not params['train']:
        load_params(params)
    print_params(params)
    file_handling(params)
    # Filter params from raw logs
    # TODO: use only params as attribute and set unlabel_label with the
    # preprocessor instead of the cli as an argument to parse
    if params['preprocess']:
        preprocess = preprocess_registry.get_preprocessor(params['logs_type'])
        preprocess(params)
    # Load filtered params from file
    print('Loading logs')
    x_data, y_data, target_names = load_logs(params)
    if params['train']:
        train(params, x_data, y_data, target_names)
    else:
        inference(params, x_data, y_data, target_names)


if __name__ == "__main__":
    main()
