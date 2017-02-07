#!/usr/bin/python
# Author: Clara Vania

import numpy as np
import tensorflow as tf
import argparse
import time
import os
import pickle
import sys
from utils import TextLoader
from biLSTM import BiLSTMModel
from lstm_redup import LSTMRedup
from charCNN import CharCNN
from add import AdditiveModel
from word import WordModel


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--train_file', type=str, default='../../data/multi/id/bpe.train.lc.txt',
                        help="training data")
    parser.add_argument('--dev_file', type=str, default='../../data/multi/id/bpe.dev.lc.txt',
                        help="development data")
    parser.add_argument('--output_vocab_file', type=str, default='',
                        help="vocab dictionary (word to id)")
    parser.add_argument('--output', '-o', type=str, default='train.log',
                        help='output file')
    parser.add_argument('--save_dir', type=str, default='model',
                        help='directory to store checkpointed models')
    parser.add_argument('--rnn_size', type=int, default=200,
                        help='size of RNN hidden state')
    parser.add_argument('--num_layers', type=int, default=2,
                        help='number of layers in the RNN')
    parser.add_argument('--num_highway', type=int, default=1,
                        help='number of highway layers (for CNN model)')
    parser.add_argument('--model', type=str, default='lstm',
                        help='rnn, gru, or lstm')
    parser.add_argument('--unit', type=str, default='morpheme',
                        help='char, char-ngram, morpheme, word, or oracle')
    parser.add_argument('--composition', type=str, default='bi-lstm',
                        help='none(word), addition, or bi-lstm')
    parser.add_argument('--lowercase', dest='lowercase', action='store_true',
                        help='lowercase data', default=False)
    parser.add_argument('--batch_size', type=int, default=32,
                        help='minibatch size')
    parser.add_argument('--num_steps', type=int, default=20,
                        help='RNN sequence length')
    parser.add_argument('--out_vocab_size', type=int, default=5000,
                        help='size of output vocabulary')
    parser.add_argument('--num_epochs', type=int, default=50,
                        help='number of epochs')
    parser.add_argument('--patience', type=int, default=3,
                        help='the number of iterations allowed before decaying the '
                             'learning rate if there is no improvement on dev set')
    parser.add_argument('--validation_interval', type=int, default=1,
                        help='validation interval')
    parser.add_argument('--init_scale', type=float, default=0.1,
                        help='initial weight scale')
    parser.add_argument('--grad_clip', type=float, default=5.0,
                        help='maximum permissible norm of the gradient')
    parser.add_argument('--learning_rate', type=float, default=1.0,
                        help='initial learning rate')
    parser.add_argument('--decay_rate', type=float, default=0.5,
                        help='the decay of the learning rate')
    parser.add_argument('--keep_prob', type=float, default=0.5,
                        help='the probability of keeping weights in the dropout layer')
    parser.add_argument('--gpu', type=int, default=0,
                        help='the gpu id, if have more than one gpu')
    parser.add_argument('--optimization', type=str, default='sgd',
                        help='sgd, momentum, or adagrad')
    parser.add_argument('--redup_list', type=str, default='',
                        help='list of reduplicated words')
    parser.add_argument('--train', type=str, default='softmax',
                        help='sgd, momentum, or adagrad')
    parser.add_argument('--SOS', type=str, default='false',
                        help='start of sentence symbol')
    parser.add_argument('--EOS', type=str, default='true',
                        help='end of sentence symbol')
    parser.add_argument('--ngram', type=int, default=3,
                        help='length of character ngram (for char-ngram model only)')
    parser.add_argument('--char_dim', type=int, default=200,
                        help='dimension of char embedding (for C2W model only)')
    parser.add_argument('--morph_dim', type=int, default=200,
                        help='dimension of morpheme embedding (for M2W model only)')
    parser.add_argument('--word_dim', type=int, default=200,
                        help='dimension of word embedding (for C2W model only)')
    parser.add_argument('--cont', type=str, default='false',
                        help='continue training')
    parser.add_argument('--seed', type=int, default=0,
                        help='seed for random initialization')
    args = parser.parse_args()
    train(args)


def run_epoch(session, m, data, data_loader, eval_op, verbose=False):
    epoch_size = ((len(data) // m.batch_size) - 1) // m.num_steps
    start_time = time.time()

    costs = 0.0
    iters = 0
    state = session.run(m.initial_lm_state)

    if data_loader.composition == "bi-lstm":
        session.run(m.initial_fw_state)
        session.run(m.initial_bw_state)

    for step, (x, y) in enumerate(data_loader.data_iterator(data, m.batch_size, m.num_steps)):
        cost, state, _ = session.run([m.cost, m.final_state, eval_op],
                                     {m.input_data: x,
                                      m.targets: y,
                                      m.initial_lm_state: state})
        costs += cost
        iters += m.num_steps

        if verbose and step % (epoch_size // 10) == 10:
            print("%.3f perplexity: %.3f speed: %.0f wps" %
                  (step * 1.0 / epoch_size, np.exp(costs / iters),
                   iters * m.batch_size / (time.time() - start_time)))

    return np.exp(costs / iters)


def run_epoch_redup(session, m, data, data_loader, eval_op, verbose=False):
    epoch_size = ((len(data) // m.batch_size) - 1) // m.num_steps
    start_time = time.time()

    costs = 0.0
    iters = 0
    state = session.run(m.initial_lm_state)

    if data_loader.composition == "bi-lstm":
        session.run(m.initial_fw_state)
        session.run(m.initial_bw_state)

    for step, (x, y, z) in enumerate(data_loader.data_iterator(data, m.batch_size, m.num_steps)):
        cost, state, _ = session.run([m.cost, m.final_state, eval_op],
                                     {m.input_data: x,
                                      m.targets: y,
                                      m.cues: z,
                                      m.initial_lm_state: state})
        costs += cost
        iters += m.num_steps

        if verbose and step % (epoch_size // 10) == 10:
            print("%.3f perplexity: %.3f speed: %.0f wps" %
                  (step * 1.0 / epoch_size, np.exp(costs / iters),
                   iters * m.batch_size / (time.time() - start_time)))

    return np.exp(costs / iters)


def train(args):
    start = time.time()
    save_dir = args.save_dir
    try:
        os.stat(save_dir)
    except:
        os.mkdir(save_dir)

    args.eos = ''
    args.sos = ''
    if args.EOS == "true":
        args.eos = '</s>'
        args.out_vocab_size += 1
    if args.SOS == "true":
        args.sos = '<s>'
        args.out_vocab_size += 1

    data_loader = TextLoader(args)
    train_data = data_loader.train_data
    dev_data = data_loader.dev_data

    fout = open(os.path.join(args.save_dir, args.output), "a")

    args.word_vocab_size = data_loader.word_vocab_size

    if args.unit != "word":
        args.subword_vocab_size = data_loader.subword_vocab_size
    fout.write(str(args) + "\n")

    # Statistics of words
    fout.write("Word vocab size: " + str(data_loader.word_vocab_size) + "\n")

    # Statistics of sub units
    if args.unit != "word":
        fout.write("Subword vocab size: " + str(data_loader.subword_vocab_size) + "\n")
        if args.composition == "bi-lstm":
            if args.unit == "char":
                fout.write("Maximum word length: " + str(data_loader.max_word_len) + "\n")
                args.bilstm_num_steps = data_loader.max_word_len
            elif args.unit == "char-ngram":
                fout.write("Maximum ngram per word: " + str(data_loader.max_ngram_per_word) + "\n")
                args.bilstm_num_steps = data_loader.max_ngram_per_word
            elif args.unit == "morpheme" or args.unit == "oracle":
                fout.write("Maximum morpheme per word: " + str(data_loader.max_morph_per_word) + "\n")
                args.bilstm_num_steps = data_loader.max_morph_per_word
            else:
                sys.exit("Wrong unit.")
        elif args.composition == "cnn":
            if args.unit == "char":
                args.max_word_length = data_loader.max_word_len
                fout.write("Maximum word length: " + str(data_loader.max_word_len) + "\n")
            else:
                sys.exit("Wrong unit.")
        elif args.composition == "addition":
            if args.unit not in ["char-ngrams", "morphemes", "oracle"]:
                sys.exit("Wrong composition.")
    else:
        if args.composition != "none":
            sys.exit("Wrong composition.")

    with open(os.path.join(args.save_dir, 'config.pkl'), 'wb') as f:
        pickle.dump(args, f)

    if args.unit == "word":
        lm_model = WordModel
    elif args.composition == "addition":
        lm_model = AdditiveModel
    elif args.composition == "bi-lstm":
        if args.redup_list:
            lm_model = LSTMRedup
        else:
            lm_model = BiLSTMModel
    elif args.composition == "cnn":
        lm_model = CharCNN
    else:
        sys.exit("Unknown unit or composition.")

    print("Begin training...")
    # gpu_options = tf.GPUOptions(per_process_gpu_memory_fraction=0.9)
    # with tf.Graph().as_default(), tf.Session(
    #         config=tf.ConfigProto(log_device_placement=False, gpu_options=gpu_options)) as sess:
    #

    with tf.Graph().as_default(), tf.Session() as sess:
        if args.seed != 0:
            tf.set_random_seed(args.seed)
            np.random.seed(seed=args.seed)

        initializer = tf.random_uniform_initializer(-args.init_scale, args.init_scale)

        # Build models
        with tf.variable_scope("model", reuse=None, initializer=initializer):
            mtrain = lm_model(args, is_training=True)
        with tf.variable_scope("model", reuse=True, initializer=initializer):
            mdev = lm_model(args, is_training=False)

        # save only the last model
        saver = tf.train.Saver(tf.all_variables(), max_to_keep=1)
        tf.initialize_all_variables().run()
        dev_pp = 10000000.0

        # save only the last model
        ckpt = tf.train.get_checkpoint_state(args.save_dir)
        if ckpt and ckpt.model_checkpoint_path:
            saver.restore(sess, ckpt.model_checkpoint_path)

        if args.cont == 'true':  # continue training from a saved model
            ckpt = tf.train.get_checkpoint_state(args.save_dir)
            if ckpt and ckpt.model_checkpoint_path:
                saver.restore(sess, ckpt.model_checkpoint_path)
            ckpt_name = ckpt.model_checkpoint_path.split('-')
            e = int(ckpt_name[2]) + 1
        else:
            # process each epoch
            e = 1

        learning_rate = args.learning_rate
        patience = args.patience

        while e <= args.num_epochs:

            print("Epoch: %d" % e)
            mtrain.assign_lr(sess, learning_rate)
            print("Learning rate: %.3f" % sess.run(mtrain.lr))

            if args.redup_list:
                train_perplexity = run_epoch_redup(sess, mtrain, train_data, data_loader, mtrain.train_op, verbose=True)
                dev_perplexity = run_epoch_redup(sess, mdev, dev_data, data_loader, tf.no_op())
            else:
                train_perplexity = run_epoch(sess, mtrain, train_data, data_loader, mtrain.train_op, verbose=True)
                dev_perplexity = run_epoch(sess, mdev, dev_data, data_loader, tf.no_op())

            print("Train Perplexity: %.3f" % train_perplexity)
            print("Valid Perplexity: %.3f" % dev_perplexity)

            # write results to file
            fout.write("Epoch: %d\n" % e)
            fout.write("Learning rate: %.3f\n" % sess.run(mtrain.lr))
            fout.write("Train Perplexity: %.3f\n" % train_perplexity)
            fout.write("Valid Perplexity: %.3f\n" % dev_perplexity)
            fout.flush()

            decrease_lr = False
            diff = dev_pp - dev_perplexity
            if diff >= 0.1:
                print("Achieve highest perplexity on dev set, save model.")
                checkpoint_path = os.path.join(save_dir, 'model.ckpt')
                saver.save(sess, checkpoint_path, global_step=e)
                print("model saved to {}".format(checkpoint_path))
                dev_pp = dev_perplexity
            else:
                decrease_lr = True

            if e > 4:
                if args.patience != 0:
                    if decrease_lr:
                        patience -= 1
                        if patience == 0:
                            learning_rate *= args.decay_rate
                            patience = args.patience
                    # decrease learning rate
                    else:
                        learning_rate *= args.decay_rate
                # decrease learning rate
                else:
                    learning_rate *= args.decay_rate

            if learning_rate < 0.0001:
                print('Learning rate too small, stop training.')
                break

            e += 1

        print("Training time: %.0f" % (time.time() - start))
        fout.write("Training time: %.0f\n" % (time.time() - start))

if __name__ == '__main__':
    main()