#!/usr/bin/env python
# -*- coding: utf-8 -*-
# FileName  : rnn_unsupervised.py
# Author    : wuqingfeng@

from __future__ import print_function
import os
import numpy as np
import random
import string
import tensorflow as tf
import zipfile
from six.moves import range

filename = "/opt/download/text8.zip"
vocabulary_size = len(string.ascii_lowercase) + 1
first_letter = ord(string.ascii_lowercase[0])
batch_size = 64
num_unrollings = 10

def read_data(filename):
    with zipfile.ZipFile(filename) as f:
        name = f.namelist()[0]
        data = tf.compat.as_str(f.read(name))
    return data

def char2id(char):
    if char in string.ascii_lowercase:
        return ord(char) - first_letter + 1
    elif char == ' ':
        return 0
    else:
        print('Unexpected character: %s' % char)
        return 0

def id2char(dictid):
    if dictid > 0:
        return chr(dictid + first_letter - 1)
    else:
        return ' '

class BatchGenerator(object):
    def __init__(self, text, batch_size, num_unrollings):
        self._text = text
        self._text_size = len(text)
        self._batch_size = batch_size
        self._num_unrollings = num_unrollings
        segment = self._text_size // batch_size
        self._cursor = [ offset * segment for offset in range(batch_size)]
        self._last_batch = self._next_batch()
    
    def _next_batch(self):
        batch = np.zeros(shape=(self._batch_size, vocabulary_size), dtype=np.float)
        for b in range(self._batch_size):
            batch[b, char2id(self._text[self._cursor[b]])] = 1.0
            self._cursor[b] = (self._cursor[b] + 1) % self._text_size
        return batch
    
    def next(self):
        batches = [self._last_batch]
        for step in range(self._num_unrollings):
            batches.append(self._next_batch())
        self._last_batch = batches[-1]
        return batches

def characters(probabilities):
    return [id2char(c) for c in np.argmax(probabilities, 1)]

def batches2string(batches):
    """Convert a sequence of batches back into their (most likely) string representation"""
    s = [''] * batches[0].shape[0]
    for b in batches:
        s = [''.join(x) for x in zip(s, characters(b))]
    return s

def logprob(predictions, labels):
    """Log-probability of the true labels in a predicted batch"""
    predictions[predictions < 1e-10] = 1e-10
    return np.sum(np.multiply(labels, -np.log(predictions))) / labels.shape[0]

def sample_distribution(distribution):
    r = random.uniform(0, 1)
    s = 0
    for i in range(len(distribution)):
        s += distribution[i]
        if s >= r:
            return i
    return len(distribution) - 1

def sample(prediction):
    """Turn a (column) prediction into 1-hot encoded samples."""
    p = np.zeros(shape=[1, vocabulary_size], dtype=np.float)
    p[0, sample_distribution(prediction[0])] = 1.0
    return p

def random_distribution():
    b = np.random.uniform(0.0, 1.0, size=[1, vocabulary_size])
    return b / np.sum(b, 1)[:,None]

def train_with_rnn():
    num_nodes = 64

    graph = tf.Graph()
    with graph.as_default():
        #Parameters
        #Input gate: input, previous output, and bias
        ix = tf.Variable(tf.truncated_normal([vocabulary_size, num_nodes], -0.1, 0.1))
        im = tf.Variable(tf.truncated_normal([num_nodes, num_nodes], -0.1, 0.1))
        ib = tf.Variable(tf.zeros([1, num_nodes]))
        #Forget gate: input, previous ouput, abd bias
        fx = tf.Variable(tf.truncated_normal([vocabulary_size, num_nodes], -0.1, 0.1))
        fm = tf.Variable(tf.truncated_normal([num_nodes, num_nodes], -0.1, 0.1))
        fb = tf.Variable(tf.zeros([1, num_nodes]))
        # Memory cell: input, state and bias.                             
        cx = tf.Variable(tf.truncated_normal([vocabulary_size, num_nodes], -0.1, 0.1))
        cm = tf.Variable(tf.truncated_normal([num_nodes, num_nodes], -0.1, 0.1))
        cb = tf.Variable(tf.zeros([1, num_nodes]))
        # Output gate: input, previous output, and bias.
        ox = tf.Variable(tf.truncated_normal([vocabulary_size, num_nodes], -0.1, 0.1))
        om = tf.Variable(tf.truncated_normal([num_nodes, num_nodes], -0.1, 0.1))
        ob = tf.Variable(tf.zeros([1, num_nodes]))
        # Variables saving state across unrollings.
        saved_output = tf.Variable(tf.zeros([batch_size, num_nodes]), trainable=False)
        saved_state = tf.Variable(tf.zeros([batch_size, num_nodes]), trainable=False)
        # Classifier weights and biases.
        w = tf.Variable(tf.truncated_normal([num_nodes, vocabulary_size], -0.1, 0.1))
        b = tf.Variable(tf.zeros([vocabulary_size]))
        
        # Definition of the cell computation
        def lstm_cell(i, o, state):
            input_gate = tf.sigmoid(tf.matmul(i, ix) + tf.matmul(o, im) + ib)
            forget_gate = tf.sigmoid(tf.matmul(i, fx) + tf.matmul(o, fm) + fb)
            update = tf.matmul(i, cx) + tf.matmul(o, cm) + cb
            state = forget_gate * state + input_gate * tf.tanh(update)
            output_gate = tf.sigmoid(tf.matmul(i, ox) + tf.matmul(o, om) + ob)
            return output_gate * tf.tanh(state), state
        
        #Input data
        train_data = list()
        for _ in range(num_unrollings + 1):
            train_data.append(tf.placeholder(tf.float32, shape=[batch_size, vocabulary_size]))
        train_inputs = train_data[:num_unrollings]
        train_labels = train_data[1:]
        
        # Unrolled LSTM loop
        outputs = list()
        output = saved_output
        state = saved_state
        for i in train_inputs:
            output, state = lstm_cell(i, output, state)
            outputs.append(output)
        
        # State saving across unrollings
        with tf.control_dependencies([saved_output.assign(output), saved_state.assign(state)]):
            logits = tf.nn.xw_plus_b(tf.concat_v2(outputs, 0), w, b)
            loss = tf.reduce_mean(tf.nn.softmax_cross_entropy_with_logits(logits, tf.concat_v2(train_labels, 0)))
            
        #optimizer
        global_step = tf.Variable(0)
        learning_rate = tf.train.exponential_decay(10.0, global_step, 5000, 0.1, staircase=True)
        optimizer = tf.train.GradientDescentOptimizer(learning_rate)
        gradients, v = zip(*optimizer.compute_gradients(loss))
        gradients, _ = tf.clip_by_global_norm(gradients, 1.25)
        optimizer = optimizer.apply_gradients(zip(gradients, v), global_step=global_step)
        
        #Predictions
        train_prediction = tf.nn.softmax(logits)
        
        #Sampling and validation eval: batch 1, no unrolling
        sample_input = tf.placeholder(tf.float32, shape=[1, vocabulary_size])
        saved_sample_output = tf.Variable(tf.zeros([1, num_nodes]))
        saved_sample_state = tf.Variable(tf.zeros([1, num_nodes]))
        reset_sample_state = tf.group(saved_sample_output.assign(tf.zeros([1, num_nodes])), saved_sample_state.assign(tf.zeros([1, num_nodes])))
        sample_output, sample_state = lstm_cell(sample_input, saved_sample_output, saved_sample_state)
        with tf.control_dependencies([saved_sample_output.assign(sample_output), saved_sample_state.assign(sample_state)]):
            sample_prediction = tf.nn.softmax(tf.nn.xw_plus_b(sample_output, w, b))

    num_steps = 7001
    summary_frequency = 100

    with tf.Session(graph=graph) as session:
        tf.global_variables_initializer().run()
        print('Initialized')
        mean_loss = 0
        for step in range(num_steps):
            batches = train_batches.next()
            feed_dict = dict()
            for i in range(num_unrollings + 1):
                feed_dict[train_data[i]] = batches[i]
            _, l, predictions, lr = session.run([optimizer, loss, train_prediction, learning_rate], feed_dict=feed_dict)
            mean_loss += l
            if step % summary_frequency == 0:
                if step > 0:
                    mean_loss = mean_loss / summary_frequency
                print('Average loss at step %d: %f learning rate: %f'% (step, mean_loss, lr))
                mean_loss = 0
                labels = np.concatenate(list(batches)[1:])
                print('Minibatch perplexity: %.2f' % float(np.exp(logprob(predictions, labels))))
                if step % (summary_frequency * 10) == 0:
                    print("=" * 80)
                    for _ in range(5):
                        feed = sample(random_distribution())
                        sentence = characters(feed)[0]
                        reset_sample_state.run()
                        for _ in range(79):
                            prediction = sample_prediction.eval({sample_input: feed})
                            feed = sample(prediction)
                            sentence += characters(feed)[0]
                        print("sentence: ", sentence)
                    print("=" * 80)
                # Measure validation set perplexity.
                reset_sample_state.run()
                valid_logprob = 0
                for _ in range(valid_size):
                    b = valid_batches.next()
                    predictions = sample_prediction.eval({sample_input: b[0]})
                    valid_logprob = valid_logprob + logprob(predictions, b[1])
                print('Validation set perplexity: %.2f' % float(np.exp(valid_logprob / valid_size)))

def train_with_singlew_lstm():
    num_nodes = 64

    graph = tf.Graph()
    with graph.as_default():
        gate_count = 4
        #Parameters
        #Input gate: input, previous output, and bias
        input_weights = tf.Variable(tf.truncated_normal([vocabulary_size, num_nodes * gate_count], -0.1, 0.1))
        output_weights = tf.Variable(tf.truncated_normal([num_nodes, num_nodes * gate_count], -0.1, 0.1))
        bias = tf.Variable(tf.zeros([1, num_nodes * gate_count]))
        # Variables saving state across unrollings.
        saved_output = tf.Variable(tf.zeros([batch_size, num_nodes]), trainable=False)
        saved_state = tf.Variable(tf.zeros([batch_size, num_nodes]), trainable=False)
        # Classifier weights and biases.
        w = tf.Variable(tf.truncated_normal([num_nodes, vocabulary_size], -0.1, 0.1))
        b = tf.Variable(tf.zeros([vocabulary_size]))
        
        # Definition of the cell computation
        def lstm_cell(i, o, state):
            values = tf.split(1, gate_count, tf.matmul(i, input_weights) + tf.matmul(o, output_weights) + bias)
            input_gate = tf.sigmoid(values[0])
            forget_gate = tf.sigmoid(values[1])
            update = values[2]
            state = forget_gate * state + input_gate * tf.tanh(update)
            output_gate = tf.sigmoid(values[3])
            return output_gate * tf.tanh(state), state
        
        #Input data
        train_data = list()
        for _ in range(num_unrollings + 1):
            train_data.append(tf.placeholder(tf.float32, shape=[batch_size, vocabulary_size]))
        train_inputs = train_data[:num_unrollings]
        train_labels = train_data[1:]
        
        # Unrolled LSTM loop
        outputs = list()
        output = saved_output
        state = saved_state
        for i in train_inputs:
            output, state = lstm_cell(i, output, state)
            outputs.append(output)
        
        # State saving across unrollings
        with tf.control_dependencies([saved_output.assign(output), saved_state.assign(state)]):
            logits = tf.nn.xw_plus_b(tf.concat_v2(outputs, 0), w, b)
            loss = tf.reduce_mean(tf.nn.softmax_cross_entropy_with_logits(logits, tf.concat_v2(train_labels, 0)))
            
        #optimizer
        global_step = tf.Variable(0)
        learning_rate = tf.train.exponential_decay(10.0, global_step, 5000, 0.1, staircase=True)
        optimizer = tf.train.GradientDescentOptimizer(learning_rate)
        gradients, v = zip(*optimizer.compute_gradients(loss))
        gradients, _ = tf.clip_by_global_norm(gradients, 1.25)
        optimizer = optimizer.apply_gradients(zip(gradients, v), global_step=global_step)
        
        #Predictions
        train_prediction = tf.nn.softmax(logits)
        
        #Sampling and validation eval: batch 1, no unrolling
        sample_input = tf.placeholder(tf.float32, shape=[1, vocabulary_size])
        saved_sample_output = tf.Variable(tf.zeros([1, num_nodes]))
        saved_sample_state = tf.Variable(tf.zeros([1, num_nodes]))
        reset_sample_state = tf.group(saved_sample_output.assign(tf.zeros([1, num_nodes])), saved_sample_state.assign(tf.zeros([1, num_nodes])))
        sample_output, sample_state = lstm_cell(sample_input, saved_sample_output, saved_sample_state)
        with tf.control_dependencies([saved_sample_output.assign(sample_output), saved_sample_state.assign(sample_state)]):
            sample_prediction = tf.nn.softmax(tf.nn.xw_plus_b(sample_output, w, b))
    
    num_steps = 7001
    summary_frequency = 100

    with tf.Session(graph=graph) as session:
        tf.global_variables_initializer().run()
        print('Initialized')
        mean_loss = 0
        for step in range(num_steps):
            batches = train_batches.next()
            feed_dict = dict()
            for i in range(num_unrollings + 1):
                feed_dict[train_data[i]] = batches[i]
            _, l, predictions, lr = session.run([optimizer, loss, train_prediction, learning_rate], feed_dict=feed_dict)
            mean_loss += l
            if step % summary_frequency == 0:
                if step > 0:
                    mean_loss = mean_loss / summary_frequency
                print('Average loss at step %d: %f learning rate: %f'% (step, mean_loss, lr))
                mean_loss = 0
                labels = np.concatenate(list(batches)[1:])
                print('Minibatch perplexity: %.2f' % float(np.exp(logprob(predictions, labels))))
                if step % (summary_frequency * 10) == 0:
                    print("=" * 80)
                    for _ in range(5):
                        feed = sample(random_distribution())
                        sentence = characters(feed)[0]
                        reset_sample_state.run()
                        for _ in range(79):
                            prediction = sample_prediction.eval({sample_input: feed})
                            feed = sample(prediction)
                            sentence += characters(feed)[0]
                        print("sentence: ", sentence)
                    print("=" * 80)
                # Measure validation set perplexity.
                reset_sample_state.run()
                valid_logprob = 0
                for _ in range(valid_size):
                    b = valid_batches.next()
                    predictions = sample_prediction.eval({sample_input: b[0]})
                    valid_logprob = valid_logprob + logprob(predictions, b[1])
                print('Validation set perplexity: %.2f' % float(np.exp(valid_logprob / valid_size)))

if __name__ == '__main__':
    text = read_data(filename)
    print('Data size %d' % len(text))
    valid_size = 1000
    valid_text = text[:valid_size]
    train_text = text[valid_size:]
    train_size = len(train_text)
    print(train_size, train_text[:64])
    print(valid_size, valid_text[:64])
    del text

    print(char2id('a'), char2id('z'), char2id(' '), char2id('ï'))
    print(id2char(1), id2char(26), id2char(0))

    train_batches = BatchGenerator(train_text, batch_size, num_unrollings)
    valid_batches = BatchGenerator(valid_text, 1, 1)

    print(batches2string(train_batches.next()))
    print(batches2string(train_batches.next()))
    print(batches2string(valid_batches.next()))
    print(batches2string(valid_batches.next()))

    train_with_rnn()
