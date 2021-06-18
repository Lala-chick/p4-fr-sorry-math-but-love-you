# 🏆To be Modellers and Beyond!

![logo2](C:\Users\iloveslowfood\Documents\workspace\p4-fr-sorry-math-but-love-you\images\logo2.png)

## Summary

- 본 대회의 주제는 수식인식이었습니다. 어쩌고 저쩌고 해가지고 이랬다

![example3](https://github.com/iloveslowfood/p4-fr-sorry-math-but-love-you/blob/master/images/example4.png?raw=true)



#### 대회 결과

* 12팀 중 1위

* Public LB Score: 0.8574 / Private LB Score: 0.6288



## Usage

### Installation

```shell
# clone repository
git clone https://github.com/bcaitech1/p4-fr-sorry-math-but-love-you.git

# install necessary tools
pip install -r requirments.txt
```

### Train

##### Train with single optimizer

```shell
$ python train.py --train_type single_opt --config_file './configs/EfficientSATRN.yaml'
```

##### Train with two optimizers for encoder and decoder

```shell
$ python train.py --train_type dual_opt --config_file './configs/EfficientSATRN.yaml'
```

##### Attach Weight & Bias logging tool

```shell
$ python train.py --train_type single_opt --project_name <PROJECTNAME> --exp_name <EXPNAME> --config_file './configs/EfficientSATRN.yaml'
```

##### Arguments

- 모델별 configuration 파일

### Inference

```shell
# Singular model inference
$ python inference.py --inference_type singular --checkpoint <MODELPATH.pth>

# Ensemble model inference
$ python inference.py --inference_type ensemble --checkpoint <MODEL1PATH.pth> <MODEL2PATH.pth> ...
```



```shell
[folder]
│
├── configs/
├── data_tools/
├── networks/
├── postprocessing/
├── schedulers/
├── utils/
├── README.md
├── requirements.txt
├── train.py
├── train_dual_opt.py
├── ensemble.py
└── inference.py
```

## Usage

### Training

```sh
python train.py
```


### Evaluation

```sh
python evaluate.py
```

[arxiv-zhang18]: https://arxiv.org/pdf/1801.03530.pdf
[CROHME]: https://www.isical.ac.in/~crohme/
[Aida]: https://www.kaggle.com/aidapearson/ocr-data
[Upstage]: https://www.upstage.ai/
[IM2LATEX]: http://lstm.seas.harvard.edu/latex/
[pytorch]: https://pytorch.org/
