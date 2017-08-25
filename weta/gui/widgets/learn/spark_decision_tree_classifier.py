from collections import OrderedDict

from Orange.widgets import widget
from pyspark.ml import classification

from weta.gui.base.spark_estimator import SparkEstimator
from weta.gui.base.spark_base import Parameter


class OWDecisionTreeClassifier(SparkEstimator, widget.OWWidget):
    priority = 201
    name = "Decision Tree"
    description = "Decision Tree Classifier Algorithm"
    icon = "../assets/DecisionTree.svg"

    box_text = "Decision Tree Classifier"

    learner = classification.DecisionTreeClassifier
    parameters = OrderedDict({
        'featuresCol': Parameter(str, 'features', 'Features column', data_column=True),
        'labelCol': Parameter(str, 'label', 'Label column', data_column=True),
        'predictionCol': Parameter(str, 'prediction', 'Prediction column', data_column=True),
        'probabilityCol': Parameter(str, "probability", 'Probability column', data_column=True),
        'rawPredictionCol': Parameter(str, 'rawPrediction', 'Raw prediction column', data_column=True),
        'maxDepth': Parameter(int, 5, 'Maximal depth'),
        'maxBins': Parameter(int, 32, 'Maximal bins'),
        'minInstancesPerNode': Parameter(int, 1, 'Minimum instance per node'),
        'minInfoGain': Parameter(float, 0.0, 'Minimum Information gain'),
        'maxMemoryInMB': Parameter(int, 256, 'Maximal Memory (MB)'),
        'cacheNodeIds': Parameter(bool, False, 'Cache node ids'),
        'checkpointInterval': Parameter(int, 10, 'Checkpoint interval'),
        'impurity': Parameter(str, 'gini', 'Impurity'),
        'seed': Parameter(int, None, 'Seed'),
    })
