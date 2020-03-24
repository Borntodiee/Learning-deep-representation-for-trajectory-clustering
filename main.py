import torch
import argparse
import time
import pdb
import os
import pickle
import numpy as np
import time

import models
import readdata
from utils import cuda, sequence_mask, MSE

parser = argparse.ArgumentParser()
parser.add_argument('-train_data', type=str, default='data/train.pkl')
parser.add_argument('-test_data', type=str, default='data/test.pkl')
parser.add_argument('-eval_size', type=float, default=0.05)
parser.add_argument('-hidden_size', type=int, default=128)
parser.add_argument('-layers', type=int, default=1)
parser.add_argument('-dropout', type=float, default=0.0)
parser.add_argument('-learning_rate', type=float, default=0.001)
parser.add_argument('-batch', type=int, default=256)
parser.add_argument('-epoch', type=int, default=15)
parser.add_argument('-print', type=int, default=20)
parser.add_argument('-save', type=int, default=2000)
parser.add_argument('-max_length', type=int, default=200)
parser.add_argument('-cuda', type=bool, default=True)
parser.add_argument('-checkpoint', type=str, default='checkpoints')
parser.add_argument('-load_state', type=str, default='')
parser.add_argument('-test_when_save', type=bool, default=True)
parser.add_argument('-save_test_result', type=bool, default=True)
parser.add_argument('-encode_savepath', type=str, default='')

args = parser.parse_args()

def eval_data(dataset, process = 0):
    all_result = []
    all_loss = []
    process = min(process, len(dataset))
    for number, [length, traj, index] in enumerate(dataset):
        traj = traj.transpose(0, 1)
        fake_input = cuda(torch.zeros((traj.shape[0], traj.shape[1], 0)).float())
        model.eval()
        result = model(traj, length, fake_input)
        raw_output = model.get_result(traj, length).cpu().detach()
        output = torch.tensor(raw_output)
        for num in range(len(raw_output)):
            output[index[num]] = raw_output[num]
        all_result.append(output)
        mask = sequence_mask(length, args.max_length).transpose(0, 1)
        eval_loss = loss(result, traj, dim = 2) * mask
        eval_loss = eval_loss.sum(dim=0) / length.float()
        all_loss.append(eval_loss.cpu().detach())
        if process > 0 and number % (len(dataset) // process) == 0:
            print('encoding %d / %d' % (number, len(dataset)))
    all_result = torch.cat(all_result)
    all_loss = torch.cat(all_loss)
    return all_result, all_loss.mean().item()

if args.encode_savepath != '':
    start_time = time.time()
    cp = torch.load(args.load_state)
    c_args = cp['args']
    c_args.load_state = args.load_state
    c_args.encode_savepath = args.encode_savepath
    c_args.test_data = args.test_data
    args = c_args
    print('checkpoint arguments loaded')
    print(args)
    print(time.time() - start_time)
    #start_time = time.time()
    testdata = readdata.readfile(args.test_data, args.batch, args.max_length, 'cut', False)
    model = cuda(models.EncoderDecoder(2, args.hidden_size, args.layers, args.dropout, False), args.cuda)
    model.load_state_dict(cp['state_dict'])
    loss = MSE
    print(time.time() - start_time)
    #start_time = time.time()
    all_test_result, all_test_loss = eval_data(testdata, 100)
    all_test_result = np.array(all_test_result)
    pickle.dump(all_test_result, open(args.encode_savepath, 'wb'))
    print(time.time() - start_time)
    exit()

print(args)

if not os.path.exists(args.checkpoint):
    os.mkdir(args.checkpoint)
if not os.path.isdir(args.checkpoint):
    print('checkpoint path exists and is not a directory! exit.')
    exit(0)

model = cuda(models.EncoderDecoder(2, args.hidden_size, args.layers, args.dropout, False), args.cuda)
traindata, evaldata = readdata.readfile(args.train_data, args.batch, args.max_length, split = 0.05)
testdata = readdata.readfile(args.test_data, args.batch, args.max_length, 'cut', False)
loss = MSE
opt = torch.optim.Adam(model.parameters(), args.learning_rate)

pdb.set_trace()

print('train data batch:', len(traindata))
print('evaluate data batch:', len(evaldata))
print('test data batch:', len(testdata))

epoch = 0
iteration = 0
best_eval_loss = 1e30
best_model_path = os.path.join(args.checkpoint, 'best_model.pt')
if os.path.exists(best_model_path):
    best_eval_loss = torch.load(best_model_path)['eval_loss']

if args.load_state != '':
    checkpoint = torch.load(args.load_state)
    epoch = checkpoint['epoch'] - 1
    iteration = checkpoint['iteration']
    checkpoint_args = checkpoint['args']
    model.load_state_dict(checkpoint['state_dict'])
    opt.load_state_dict(checkpoint['opt_state_dict'])

ite_start_time = time.time()
for epoch in range(epoch + 1, args.epoch + 1):
    print('start epoch %4d' % epoch)
    for length, traj, index in traindata:
        traj = traj.transpose(0, 1)
        fake_input = cuda(torch.zeros((traj.shape[0], traj.shape[1], 0)).float())
        model.train()
        opt.zero_grad()
        result = model(traj, length, fake_input)
        mask = sequence_mask(length, args.max_length).transpose(0, 1)
        l = loss(result, traj, dim = 2) * mask
        l = (l.sum(dim=0) / length.float()).mean()
        l.backward()
        opt.step()
        iteration += 1
        if iteration % args.print == 0:
            model.eval()
            _, eval_loss = eval_data(evaldata)
            print('iteration %d: train_loss:%.10f eval_loss:%.10f time:%.2f' % (iteration, l, eval_loss, time.time() - ite_start_time))
            ite_start_time = time.time()
        if iteration % args.save == 0:
            _, all_eval_loss = eval_data(evaldata)
            all_test_result = None
            all_test_loss = None
            if args.test_when_save:
                all_test_result, all_test_loss = eval_data(testdata)
                if not args.save_test_result:
                    all_test_result = None
            filename = '%06d.pt' % iteration
            filename = os.path.join(args.checkpoint, filename)
            savedata = {
                'epoch': epoch,
                'iteration': iteration,
                'train_loss': l,
                'eval_loss': all_eval_loss,
                'test_loss': all_test_loss,
                'test_result': all_test_result,
                'args': args,
                'state_dict': model.state_dict(),
                'opt_state_dict': opt.state_dict()
            }
            torch.save(savedata, filename)
            print('checkpoint %s saved. test_loss: %s' % (filename, str(all_test_loss)))
            if all_eval_loss < best_eval_loss:
                best_eval_loss = all_eval_loss
                torch.save(savedata, best_model_path)
                print('best model updated')

