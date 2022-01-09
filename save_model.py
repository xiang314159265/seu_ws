import argparse
import os
from functools import partial

import numpy as np
import paddle
import paddle.nn.functional as F
from paddlenlp.data import Stack, Tuple, Pad
from paddlenlp.transformers import SkepForSequenceClassification

# yapf: disable
parser = argparse.ArgumentParser()
parser.add_argument("--params_path", type=str, required=False,
    default='./checkpoint/model_16838/model_state.pdparams',
    help="The path to model parameters to be loaded.")
parser.add_argument("--output_path", type=str, default='./static_graph_params',
    help="The path of model parameter in static graph to be saved.")
parser.add_argument('--model_name', choices=['skep_ernie_1.0_large_ch', 'skep_ernie_2.0_large_en'],
    default="skep_ernie_2.0_large_en", help="Select which model to train, defaults to skep_ernie_1.0_large_ch.")
args = parser.parse_args()
# yapf: enable

if __name__ == "__main__":
    # The number of labels should be in accordance with the training dataset.
    label_map = {0: 'negative', 1: 'positive'}
    model = SkepForSequenceClassification.from_pretrained(
        args.model_name, num_classes=len(label_map))

    if args.params_path and os.path.isfile(args.params_path):
        state_dict = paddle.load(args.params_path)
        model.set_dict(state_dict)
        print("Loaded parameters from %s" % args.params_path)
    model.eval()

    # Convert to static graph with specific input description
    model = paddle.jit.to_static(
        model,
        input_spec=[
            paddle.static.InputSpec(
                shape=[None, None], dtype="int64"),  # input_ids
            paddle.static.InputSpec(
                shape=[None, None], dtype="int64")  # segment_ids
        ])
    # Save in static graph model.
    paddle.jit.save(model, args.output_path)