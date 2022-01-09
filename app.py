import os
os.environ["TF_CPP_MIN_LOG_LEVEL"] = "2"
from flask import Flask
from flask import url_for, escape,render_template,request,redirect
import pythoncom
import werkzeug
import docx
from win32com import client as wc

app = Flask(__name__)

import codecs

import argparse

import numpy as np
import paddle
import paddlenlp as ppnlp
from scipy.special import softmax
from paddle import inference
from paddlenlp.data import Stack, Tuple, Pad

# yapf: disable
parser = argparse.ArgumentParser()
parser.add_argument("--model_file", type=str, required=False, default='./static_graph_params.pdmodel', help="The path to model info in static graph.")
parser.add_argument("--params_file", type=str, required=False, default='./static_graph_params.pdiparams', help="The path to parameters in static graph.")

parser.add_argument("--max_seq_length", default=128, type=int, help="The maximum total input sequence length after tokenization. "
    "Sequences longer than this will be truncated, sequences shorter will be padded.")
parser.add_argument("--batch_size", default=2, type=int, help="Batch size per GPU/CPU for training.")
parser.add_argument('--device', choices=['cpu', 'gpu', 'xpu'], default="gpu", help="Select which device to train model, defaults to gpu.")
parser.add_argument('--model_name', choices=['skep_ernie_1.0_large_ch', 'skep_ernie_2.0_large_en'],
    default="skep_ernie_2.0_large_en", help="Select which model to train, defaults to skep_ernie_1.0_large_ch.")
args = parser.parse_args()
# yapf: enable


def convert_example(example,
                    tokenizer,
                    label_list,
                    max_seq_length=512,
                    is_test=False):
    text = example
    encoded_inputs = tokenizer(text=text, max_seq_len=max_seq_length)
    input_ids = np.array(encoded_inputs['input_ids'], dtype="int64")
    token_type_ids = np.array(encoded_inputs['token_type_ids'], dtype="int64")
    return input_ids, token_type_ids


class Predictor(object):
    def __init__(self, model_file, params_file, device, max_seq_length):
        self.max_seq_length = max_seq_length

        config = paddle.inference.Config(model_file, params_file)
        if device == "gpu":
            # set GPU configs accordingly
            config.enable_use_gpu(100, 0)
        elif device == "cpu":
            # set CPU configs accordingly,
            # such as enable_mkldnn, set_cpu_math_library_num_threads
            config.disable_gpu()
        elif device == "xpu":
            # set XPU configs accordingly
            config.enable_xpu(100)
        config.switch_use_feed_fetch_ops(False)
        self.predictor = paddle.inference.create_predictor(config)

        self.input_handles = [
            self.predictor.get_input_handle(name)
            for name in self.predictor.get_input_names()
        ]

        self.output_handle = self.predictor.get_output_handle(
            self.predictor.get_output_names()[0])

    def predict_sentiment(self, input, tokenizer, label_map, batch_size=1):
        """
        Predicts the data labels.
        Args:
            model (obj:`paddle.nn.Layer`): A model to classify texts.
            data (obj:`List(Example)`): The processed data whose each element is a Example (numedtuple) object.
                A Example object contains `text`(word_ids) and `se_len`(sequence length).
            tokenizer(obj:`PretrainedTokenizer`): This tokenizer inherits from :class:`~paddlenlp.transformers.PretrainedTokenizer`
                which contains most of the methods. Users should refer to the superclass for more information regarding methods.
            label_map(obj:`dict`): The label id (key) to label str (value) map.
            batch_size(obj:`int`, defaults to 1): The number of batch.
        Returns:
            results(obj:`dict`): All the predictions labels.
        """
        examples = []
        data=[]
        data.append(input)
        for text in data:
            input_ids, segment_ids = convert_example(
                text,
                tokenizer,
                label_list=label_map.values(),
                max_seq_length=self.max_seq_length,
                is_test=True)
            examples.append((input_ids, segment_ids))

        batchify_fn = lambda samples, fn=Tuple(
            Pad(axis=0, pad_val=tokenizer.pad_token_id),  # input
            Pad(axis=0, pad_val=tokenizer.pad_token_id),  # segment
        ): fn(samples)

        # Seperates data into some batches.
        batches = [
            examples[idx:idx + batch_size]
            for idx in range(0, len(examples), batch_size)
        ]

        results = []
        for batch in batches:
            input_ids, segment_ids = batchify_fn(batch)
            self.input_handles[0].copy_from_cpu(input_ids)
            self.input_handles[1].copy_from_cpu(segment_ids)
            self.predictor.run()
            logits = self.output_handle.copy_to_cpu()
            probs = softmax(logits, axis=1)
            idx = np.argmax(probs, axis=1)
            idx = idx.tolist()
            labels = [label_map[i] for i in idx]
            results.extend(labels)
        return results

predictor = Predictor(args.model_file, args.params_file, args.device,
                          args.max_seq_length)

tokenizer = ppnlp.transformers.SkepTokenizer.from_pretrained(
        args.model_name)
label_map = {0: 'negative', 1: 'positive'}

def save_doc_to_docx(filepath,basename):  # doc转docx
    if filepath.endswith('.doc') and not filepath.startswith('~$'):
        pythoncom.CoInitialize()
        word = wc.Dispatch("Word.Application")
        print(filepath)
        # try
        # 打开文件
        doc = word.Documents.Open(filepath)
        # # 将文件名与后缀分割
        rename = os.path.splitext(filepath)
        print(rename[0] + '.docx')
        # 将文件另存为.docx
        doc.SaveAs(rename[0] + '.docx', 12)  # 12表示docx格式
        doc.Close()
        word.Quit()
        return rename[0] + '.docx'
    return filepath

@app.route('/')
@app.route('/index')
@app.route('/index.html')
def hello():
    return render_template('index.html')


@app.route('/uploadword',methods=['POST','GET'])
@app.route('/uploadword.html',methods=['POST','GET'])
def uploadword():
    if request.method == 'POST':
        f = request.files['file']
        basepath = os.path.dirname(__file__)  # 当前文件所在路径
        upload_path = os.path.join(basepath, 'upload', f.filename)  # 注意：没有的文件夹一定要先创建，不然会提示没有该路径
        f.save(upload_path)
        location=os.path.join(basepath,'upload')
        upload_path=save_doc_to_docx(upload_path,location)
        file=docx.Document(upload_path)
        text=''
        for para in file.paragraphs:
            text += para.text
        result=predictor.predict_sentiment(
        text, tokenizer, label_map, batch_size=args.batch_size)
        emotion=result[0]
        return render_template('uploadword.html', emotion=emotion, text=text)
    return render_template('uploadword.html')

@app.route('/input')
@app.route('/input.html')
def input():
    return render_template('input.html')

@app.route('/uploadtxt',methods=['POST','GET'])
@app.route('/uploadtxt.html',methods=['POST','GET'])
def uploadtxt():
    print(request.method)
    if request.method == 'POST':
        f = request.files['file']
        basepath = os.path.dirname(__file__)  # 当前文件所在路径
        upload_path = os.path.join(basepath, 'upload',f.filename)  # 注意：没有的文件夹一定要先创建，不然会提示没有该路径
        f.save(upload_path)
        with open(upload_path, encoding='utf-8') as f:
            text=f.read()
        result = predictor.predict_sentiment(
            text, tokenizer, label_map, batch_size=args.batch_size)
        emotion=result[0]
        return render_template('uploadtxt.html',emotion=emotion,text=text)
    return render_template('uploadtxt.html')

@app.route('/input_analyze',methods=['POST'])
def input_analyze():
    text=request.form.get('text')
    result = predictor.predict_sentiment(
        text, tokenizer, label_map, batch_size=args.batch_size)
    emotion=result[0]
    return render_template('input.html',emotion=emotion,text=text)

if __name__ == '__main__':
    app.run(debug=True)