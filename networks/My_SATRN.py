import torch
import torch.nn as nn
import torch.nn.functional as F
import numpy as np
import math
import random
import timm

from dataset import START, PAD

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")


class ShallowCNN(nn.Module):
    def __init__(self, input_channels, hidden_size):
        super(ShallowCNN, self).__init__()
        self.conv0 = nn.Conv2d(input_channels, hidden_size//2, 3, bias=False, padding=1)
        self.batch_norm0 = nn.BatchNorm2d(hidden_size//2)
        self.relu0 = nn.ReLU()
        self.pool0 = nn.MaxPool2d(kernel_size=2, stride=2)

        self.conv1 = nn.Conv2d(hidden_size//2, hidden_size, 3, bias=False, padding=1)
        self.batch_norm1 = nn.BatchNorm2d(hidden_size)
        self.relu1 = nn.ReLU()
        self.pool1 = nn.MaxPool2d(kernel_size=2, stride=2)

        self.conv2 = nn.Conv2d(hidden_size, hidden_size ,3, bias=False, padding=1)
        self.batch_norm2 = nn.BatchNorm2d(hidden_size)
        self.relu2 = nn.ReLU()
        self.pool2 = nn.MaxPool2d(kernel_size=2, stride=2)

        torch.nn.init.xavier_normal_(self.conv0.weight)
        torch.nn.init.xavier_normal_(self.conv1.weight)
        torch.nn.init.xavier_normal_(self.conv2.weight)
        
    def forward(self, x):
        x = self.conv0(x)
        x = self.batch_norm0(x)
        x = self.relu0(x)
        x = self.pool0(x)

        x = self.conv1(x)
        x = self.batch_norm1(x)
        x = self.relu1(x)
        x = self.pool1(x)

        x = self.conv2(x)
        x = self.batch_norm2(x)
        x = self.relu2(x)
        x = self.pool2(x)

        return x # (batch, hidden_size, h/8, w/8)

class CustomCNN(nn.Module):
    def __init__(self, input_channel, output_channel):
        super(CustomCNN, self).__init__()
        m = timm.create_model('tf_efficientnetv2_s_in21ft1k', pretrained=True)
        self.conv_stem= nn.Conv2d(input_channel, 24, kernel_size=(3, 3), stride=(2, 2), bias=False)
        self.bn1 = nn.BatchNorm2d(24, eps=0.001, momentum=0.1, affine=True, track_running_stats=True)
        self.act1 = nn.SiLU(inplace=True)
        self.eff_block = m.blocks
        self.conv_last = nn.Conv2d(256, output_channel, kernel_size=(1,1), stride=(1,1), bias=False)
        self.bn2 = nn.BatchNorm2d(output_channel)
        self.act2 = nn.SiLU(inplace=True)

    def forward(self, x):

        x = self.conv_stem(x)
        x = self.act1(self.bn1(x))
        x = self.eff_block(x)
        x = self.conv_last(x)
        x = self.act2(self.bn2(x))

        return x #[b, c, h/32, w/32]

class PositionalEncoding(nn.Module):
    def __init__(self, hidden_size, h=128, w=128, dropout=0.1):
        super(PositionalEncoding, self).__init__()
        ## hidden_size < h,w면 nan값 출력 -> input channel이 h,w보다 커야함
        self.hidden_size = hidden_size
        self.h_pos_encoding = self.get_position_encoding(h, hidden_size)
        self.w_pos_encoding = self.get_position_encoding(w, hidden_size)

        self.h_pos_encoding = self.h_pos_encoding.unsqueeze(1)
        self.w_pos_encoding = self.w_pos_encoding.unsqueeze(0)

        self.dropout = nn.Dropout(p=dropout)
        self.dense0 = nn.Linear(hidden_size, hidden_size//2)
        self.relu = nn.ReLU()

        self.dense1 = nn.Linear(hidden_size//2, hidden_size*2)
        self.sigmoid = nn.Sigmoid()

        torch.nn.init.xavier_normal_(self.dense0.weight)
        torch.nn.init.xavier_normal_(self.dense1.weight)

    def get_position_encoding(self, length, hidden_size, min_timescale=1.0, max_timescale=1.0e4):
        position = torch.arange(length).float()
        num_timescales = [hidden_size // 2]
        log_timescale_incretement = (
            math.log(float(max_timescale) / float(min_timescale)) / (torch.FloatTensor(num_timescales) - 1)
        )
        inv_timescales = min_timescale * torch.exp(torch.FloatTensor(torch.arange(num_timescales[0]) * -log_timescale_incretement))
        scaled_time = torch.unsqueeze(position, 1) * torch.unsqueeze(inv_timescales, 0)
        signal = torch.cat((torch.sin(scaled_time), torch.cos(scaled_time)), axis=1)

        return signal
    
    def tiling(self, arr, b, c, h, w):
        arr_numpy = arr.numpy()
        arr_tile = np.tile(arr_numpy,(b,c,h,w))

        return torch.from_numpy(arr_tile)
    
    def forward(self, x):
        features = x
        b,c,h,w = x.size()

        h_encoding = self.tiling(self.h_pos_encoding.unsqueeze(0), b, 1, 1, 1).to(device)
        # print(h_encoding.shape)
        w_encoding = self.tiling(self.w_pos_encoding.unsqueeze(0), b, 1, 1, 1).to(device)
        # print
        x = torch.mean(x, [2, 3])
        x = self.dense0(x)
        x = self.relu(x)
        x = self.dropout(x)

        x = self.dense1(x)
        x = self.sigmoid(x)
        x = torch.reshape(x, [-1, 2, 1, self.hidden_size])
        x = x[:,0:1, : ,:] * h_encoding + x[:,1:2,:,:]*w_encoding
        x = x.permute(0, 3, 1, 2)
        # print(x.shape)

        return x + features #(batch, hidden_size, h, w)

class ScaledDotProductAttention(nn.Module):
    def __init__(self, temperature, dropout=0.1):
        super(ScaledDotProductAttention, self).__init__()

        self.temperature = temperature
        self.dropout = nn.Dropout(p=dropout)

    def forward(self, q, k, v, mask=None):

        attn = torch.matmul(q, k.transpose(2, 3)) / self.temperature
        if mask is not None:
            attn = attn.masked_fill(mask=mask, value=float("-inf"))
        attn = torch.softmax(attn, dim=-1)
        attn = self.dropout(attn)
        out = torch.matmul(attn, v)
        return out, attn


class MultiHeadAttention(nn.Module):
    def __init__(self, q_channels, k_channels, head_num=8, dropout=0.1):
        super(MultiHeadAttention, self).__init__()

        self.q_channels = q_channels
        self.k_channels = k_channels
        self.head_dim = q_channels // head_num
        self.head_num = head_num

        self.q_linear = nn.Linear(q_channels, self.head_num * self.head_dim)
        self.k_linear = nn.Linear(k_channels, self.head_num * self.head_dim)
        self.v_linear = nn.Linear(k_channels, self.head_num * self.head_dim)
        self.attention = ScaledDotProductAttention(
            temperature=(self.head_num * self.head_dim) ** 0.5, dropout=dropout
        )
        self.out_linear = nn.Linear(self.head_num * self.head_dim, q_channels)
        self.dropout = nn.Dropout(p=dropout)

        torch.nn.init.xavier_normal_(self.q_linear.weight)
        torch.nn.init.xavier_normal_(self.k_linear.weight)
        torch.nn.init.xavier_normal_(self.v_linear.weight)
        torch.nn.init.xavier_normal_(self.out_linear.weight)

    def forward(self, q, k, v, mask=None):
        b, q_len, k_len, v_len = q.size(0), q.size(1), k.size(1), v.size(1)
        q = (
            self.q_linear(q)
            .view(b, q_len, self.head_num, self.head_dim)
            .transpose(1, 2)
        )
        k = (
            self.k_linear(k)
            .view(b, k_len, self.head_num, self.head_dim)
            .transpose(1, 2)
        )
        v = (
            self.v_linear(v)
            .view(b, v_len, self.head_num, self.head_dim)
            .transpose(1, 2)
        )

        if mask is not None:
            mask = mask.unsqueeze(1)

        out, attn = self.attention(q, k, v, mask=mask)
        out = (
            out.transpose(1, 2)
            .contiguous()
            .view(b, q_len, self.head_num * self.head_dim)
        )
        out = self.out_linear(out)
        out = self.dropout(out)

        return out

class EncoderLayer(nn.Module):
    def __init__(self, hidden_size, filter_size, head_num, dropout_rate=0.2):
        super(EncoderLayer, self).__init__()

        self.norm = nn.LayerNorm(hidden_size)
        self.attention_layer = MultiHeadAttention(
            q_channels=hidden_size,
            k_channels=hidden_size,
            head_num=head_num,
            dropout=dropout_rate,
        )
        self.dropout0 = nn.Dropout(dropout_rate)
        self.conv0 = nn.Conv2d(hidden_size, filter_size, 1, bias=False)
        self.norm0 = nn.BatchNorm2d(filter_size)
        self.depthwise = nn.Conv2d(filter_size, filter_size,
                                    kernel_size=3, padding=1, groups=filter_size)
        self.depthwise_norm = nn.BatchNorm2d(filter_size)
        self.conv1 = nn.Conv2d(filter_size, hidden_size, 1, bias=False)
        self.norm1 = nn.BatchNorm2d(hidden_size)
        self.relu0 = nn.ReLU()
        self.relu_depth = nn.ReLU()
        self.relu1 = nn.ReLU()

        torch.nn.init.xavier_normal_(self.conv0.weight)
        torch.nn.init.xavier_normal_(self.depthwise.weight)
        torch.nn.init.xavier_normal_(self.conv1.weight)

    def forward(self, x):
        features = x
        b, c, h, w = x.size()
        x = x.view(b, c, h * w).transpose(1, 2)
        flattend_features = x

        x = self.norm(x)
        x = self.attention_layer(x, x, x)
        x = self.dropout0(x)
        x = self.norm(x + flattend_features)
        x = x.reshape(-1, c, h, w)

        x = self.conv0(x)
        x = self.norm0(x)
        x = self.relu0(x)
        x = self.depthwise(x)
        x = self.depthwise_norm(x)
        x = self.relu_depth(x)
        x = self.conv1(x)
        x = self.norm1(x)
        x = self.relu1(x)

        return x + features # (batch, hidden_size, h, w)

class SATRNEncoder(nn.Module):
    def __init__(self, 
        input_height,
        input_width,
        input_channel, 
        hidden_size, 
        filter_size,
        head_num,
        layer_num,
        dropout_rate=0.1,
        checkpoint=None,
    ):
        super(SATRNEncoder, self).__init__()

        # self.shallow_cnn = ShallowCNN(input_channel, hidden_size)
        self.shallow_cnn = CustomCNN(input_channel, hidden_size)
        self.positional_encoding = PositionalEncoding(hidden_size, 
                                                    h=input_height//32, 
                                                    w=input_width//32, 
                                                    dropout=dropout_rate)
        self.attention_layers = nn.ModuleList(
            [
                EncoderLayer(hidden_size, filter_size, head_num, dropout_rate)
                for _ in range(layer_num)
            ]
        )
        if checkpoint is not None:
            self.load_state_dict(checkpoint)
    
    def forward(self, x):
        # x - [b, c, h, w]
        out = self.shallow_cnn(x)  # [b, c, h//4, w//4]
        out = self.positional_encoding(out)  # [b, c, h//4, w//4]

        for layer in self.attention_layers:
            out = layer(out)

        # flatten
        b, c, h, w = out.size()
        out = out.view(b, c, h * w).transpose(1, 2)  # [b, h x w, c]

        return out


class Feedforward(nn.Module):
    def __init__(self, filter_size=2048, hidden_dim=512, dropout=0.1):
        super(Feedforward, self).__init__()

        # self.layers = nn.Sequential(
        #     nn.Linear(hidden_dim, filter_size, True),
        #     nn.ReLU(True),
        #     nn.Dropout(p=dropout),
        #     nn.Linear(filter_size, hidden_dim, True),
        #     nn.ReLU(True),
        #     nn.Dropout(p=dropout),
        # )

        self.linear0 = nn.Linear(hidden_dim, filter_size, True)
        self.relu0 = nn.ReLU()
        self.dropout0 = nn.Dropout(p=dropout)
        self.linear1 = nn.Linear(filter_size, hidden_dim, True)
        self.relu1 = nn.ReLU()
        self.dropout1 = nn.Dropout(p=dropout)

        torch.nn.init.xavier_normal_(self.linear0.weight)
        torch.nn.init.xavier_normal_(self.linear1.weight)

    def forward(self, input):
        # return self.layers(input)

        x = self.linear0(input)
        x = self.relu0(x)
        x = self.dropout0(x)
        x = self.linear1(x)
        x = self.relu1(x)
        x = self.dropout1(x)

        return x

class TransformerDecoderLayer(nn.Module):
    def __init__(self, input_size, src_size, filter_size, head_num, dropout_rate=0.2):
        super(TransformerDecoderLayer, self).__init__()

        self.self_attention_layer = MultiHeadAttention(
            q_channels=input_size,
            k_channels=input_size,
            head_num=head_num,
            dropout=dropout_rate,
        )
        self.self_attention_norm = nn.LayerNorm(normalized_shape=input_size)

        self.attention_layer = MultiHeadAttention(
            q_channels=input_size,
            k_channels=src_size,
            head_num=head_num,
            dropout=dropout_rate,
        )
        self.attention_norm = nn.LayerNorm(normalized_shape=input_size)

        self.feedforward_layer = Feedforward(
            filter_size=filter_size, hidden_dim=input_size
        )
        self.feedforward_norm = nn.LayerNorm(normalized_shape=input_size)

    def forward(self, tgt, tgt_prev, src, tgt_mask):

        if tgt_prev == None:  # Train
            att = self.self_attention_layer(tgt, tgt, tgt, tgt_mask)
            out = self.self_attention_norm(att + tgt)

            att = self.attention_layer(tgt, src, src)
            out = self.attention_norm(att + out)

            ff = self.feedforward_layer(out)
            out = self.feedforward_norm(ff + out)
        else:
            tgt_prev = torch.cat([tgt_prev, tgt], 1)
            att = self.self_attention_layer(tgt, tgt_prev, tgt_prev, tgt_mask)
            out = self.self_attention_norm(att + tgt)

            att = self.attention_layer(tgt, src, src)
            out = self.attention_norm(att + out)

            ff = self.feedforward_layer(out)
            out = self.feedforward_norm(ff + out)
        return out


class PositionEncoder1D(nn.Module):
    def __init__(self, in_channels, max_len=500, dropout=0.1):
        super(PositionEncoder1D, self).__init__()

        self.position_encoder = self.generate_encoder(in_channels, max_len)
        self.position_encoder = self.position_encoder.unsqueeze(0)
        self.dropout = nn.Dropout(p=dropout)

    def generate_encoder(self, in_channels, max_len):
        pos = torch.arange(max_len).float().unsqueeze(1)

        i = torch.arange(in_channels).float().unsqueeze(0)
        angle_rates = 1 / torch.pow(10000, (2 * (i // 2)) / in_channels)

        position_encoder = pos * angle_rates
        position_encoder[:, 0::2] = torch.sin(position_encoder[:, 0::2])
        position_encoder[:, 1::2] = torch.cos(position_encoder[:, 1::2])

        return position_encoder

    def forward(self, x, point=-1):
        if point == -1:
            out = x + self.position_encoder[:, : x.size(1), :].to(x.get_device())
            out = self.dropout(out)
        else:
            out = x + self.position_encoder[:, point, :].unsqueeze(1).to(x.get_device())
        return out


class SATRNDecoder(nn.Module):
    def __init__(
        self,
        num_classes,
        src_dim,
        hidden_dim,
        filter_dim,
        head_num,
        dropout_rate,
        pad_id,
        st_id,
        layer_num=1,
        checkpoint=None,
    ):
        super(SATRNDecoder, self).__init__()

        self.embedding = nn.Embedding(num_classes + 1, hidden_dim)
        self.hidden_dim = hidden_dim
        self.filter_dim = filter_dim
        self.num_classes = num_classes
        self.layer_num = layer_num

        self.pos_encoder = PositionEncoder1D(
            in_channels=hidden_dim, dropout=dropout_rate
        )

        self.attention_layers = nn.ModuleList(
            [
                TransformerDecoderLayer(
                    hidden_dim, src_dim, filter_dim, head_num, dropout_rate
                )
                for _ in range(layer_num)
            ]
        )
        self.generator = nn.Linear(hidden_dim, num_classes)

        self.pad_id = pad_id
        self.st_id = st_id

        if checkpoint is not None:
            self.load_state_dict(checkpoint)

    def pad_mask(self, text):
        pad_mask = text == self.pad_id
        pad_mask[:, 0] = False
        pad_mask = pad_mask.unsqueeze(1)

        return pad_mask

    def order_mask(self, length):
        order_mask = torch.triu(torch.ones(length, length), diagonal=1).bool()
        order_mask = order_mask.unsqueeze(0).to(device)
        return order_mask

    def text_embedding(self, texts):
        tgt = self.embedding(texts)
        tgt *= math.sqrt(tgt.size(2))

        return tgt

    def forward(
        self, src, text, is_train=True, batch_max_length=50, teacher_forcing_ratio=1.0
    ):

        if is_train and random.random() < teacher_forcing_ratio:
            tgt = self.text_embedding(text)
            tgt = self.pos_encoder(tgt)
            tgt_mask = self.pad_mask(text) | self.order_mask(text.size(1))
            for layer in self.attention_layers:
                tgt = layer(tgt, None, src, tgt_mask)
            out = self.generator(tgt)
        else:
            out = []
            num_steps = batch_max_length - 1
            target = torch.LongTensor(src.size(0)).fill_(self.st_id).to(device) # [START] token
            features = [None] * self.layer_num

            for t in range(num_steps):
                target = target.unsqueeze(1)
                tgt = self.text_embedding(target)
                tgt = self.pos_encoder(tgt, point=t)
                tgt_mask = self.order_mask(t + 1)
                tgt_mask = tgt_mask[:, -1].unsqueeze(1)  # [1, (l+1)]
                for l, layer in enumerate(self.attention_layers):
                    tgt = layer(tgt, features[l], src, tgt_mask)
                    features[l] = (
                        tgt if features[l] == None else torch.cat([features[l], tgt], 1)
                    )

                _out = self.generator(tgt)  # [b, 1, c]
                target = torch.argmax(_out[:, -1:, :], dim=-1)  # [b, 1]
                target = target.squeeze()   # [b]
                out.append(_out)
            
            out = torch.stack(out, dim=1).to(device)    # [b, max length, 1, class length]
            out = out.squeeze(2)    # [b, max length, class length]

        return out


class MySATRN(nn.Module):
    def __init__(self, FLAGS, train_dataset, checkpoint=None):
        super(MySATRN, self).__init__()

        self.encoder = SATRNEncoder(
            input_height=FLAGS.input_size.height,
            input_width=FLAGS.input_size.width,
            input_channel=FLAGS.data.rgb,
            hidden_size=FLAGS.SATRN.encoder.hidden_dim,
            filter_size=FLAGS.SATRN.encoder.filter_dim,
            head_num=FLAGS.SATRN.encoder.head_num,
            layer_num=FLAGS.SATRN.encoder.layer_num,
            dropout_rate=FLAGS.dropout_rate,
        )

        self.decoder = SATRNDecoder(
            num_classes=len(train_dataset.id_to_token),
            src_dim=FLAGS.SATRN.decoder.src_dim,
            hidden_dim=FLAGS.SATRN.decoder.hidden_dim,
            filter_dim=FLAGS.SATRN.decoder.filter_dim,
            head_num=FLAGS.SATRN.decoder.head_num,
            dropout_rate=FLAGS.dropout_rate,
            pad_id=train_dataset.token_to_id[PAD],
            st_id=train_dataset.token_to_id[START],
            layer_num=FLAGS.SATRN.decoder.layer_num,
        )

        self.criterion = (
            nn.CrossEntropyLoss()
        )  # without ignore_index=train_dataset.token_to_id[PAD]

        if checkpoint:
            self.load_state_dict(checkpoint)

    def forward(self, input, expected, is_train, teacher_forcing_ratio):
        enc_result = self.encoder(input)
        dec_result = self.decoder(
            enc_result,
            expected[:, :-1],
            is_train,
            expected.size(1),
            teacher_forcing_ratio,
        )
        return dec_result


        