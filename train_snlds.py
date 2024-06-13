# Simple script to train a 2D SDS
import sys
import time

import numpy as np
import torch
from torch.autograd import Variable
from torch.utils.data import DataLoader, TensorDataset

from generate_data_and_train_snlds import save_checkpoint
from models.modules import MLP
from models.VariationalSNLDS import VariationalSNLDS

# Data generation settings
device = 'cuda:1'
data_type = 'cosine'
data_size = 5000
T = 200
dim_obs = 2
dim_latent = 2
num_states = 3
sparsity_prob = 0.0
seed = 23
# Train settings (no temperature annealing)
final_temperature = 1
pre_train_check = 5
epoch_num = 100
learning_rate = 5e-4
gamma_decay = 0.5
scheduler_epochs = 40

path = 'data/latent_variables/obs_train_N_{}_T_{}_dim_latent_{}_dim_obs_{}_state_{}_sparsity_{}_net_{}_seed_{}.npy'.format(data_size,T, dim_latent, dim_obs, num_states, sparsity_prob, data_type, seed)
dl = TensorDataset(torch.from_numpy(np.load(path)))

# Training for 10 restarts
for restart_num in range(10):
    best_elbo = -torch.inf
    dataloader = DataLoader(dl, batch_size=50, shuffle=True)
    model = VariationalSNLDS(dim_obs, dim_latent, 64, num_states, encoder_type='recurent', device=device, annealing=False, inference='alpha', beta=0)
    # Useful for setting a smaller transition network to avoid overfitting
    model.transitions = torch.nn.ModuleList([MLP(dim_latent, dim_latent, 16, 'cos') for _ in range(num_states)]).to(device).float()
    model.temperature = final_temperature
    model.beta = 0
    optimizer = torch.optim.Adam(model.parameters(), lr=learning_rate)
    scheduler = torch.optim.lr_scheduler.StepLR(optimizer, step_size=scheduler_epochs, gamma=gamma_decay)
    mse = 1e5
    model.Q.requires_grad_(False)
    model.pi.requires_grad_(False)
    for epoch in range(0, epoch_num):
        if epoch >= pre_train_check and mse > 6e3:
            break
        if epoch >= pre_train_check and epoch < scheduler_epochs//4:
            model.beta = 1
        elif epoch >= scheduler_epochs//4:
            model.Q.requires_grad_(True)
            model.pi.requires_grad_(True)
        end = time.time()
        for i, (sample,) in enumerate(dataloader, 1):
            B, T, D = sample.size()
            obs_var = Variable(sample[:,:].float(), requires_grad=True).to(device)
            optimizer.zero_grad()
            x_hat, _, _, losses = model(obs_var)
            # Compute loss and optimize params
            losses['loss'].backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 5.0)
            optimizer.step()
            mse = torch.nn.functional.mse_loss(x_hat, obs_var, reduction='sum')/(B)
            batch_time = time.time() - end
            end = time.time()   
            if i%10==0:
                print('Epoch: [{0}][{1}/{2}]\t'
                    'Time {batch_time:.3f}\t'
                    'ELBO {loss:.4e}\t MSE: {mse:.4e}\t MSM: {msm:.4e}'.format(
                    epoch, i, len(dataloader), batch_time=batch_time, 
                    loss=losses['elbo'], mse=mse, msm=losses['msm_loss']))
                sys.stdout.flush()

        if epoch%2==0:
            print((model.Q/model.temperature).softmax(-1))
            print((model.pi/model.temperature).softmax(-1))
            print(model.temperature)
        sys.stdout.flush()
        scheduler.step()
        save_checkpoint({
            'epoch': epoch,
            'model': model.state_dict()
        }, filename='test_network_restart_{:02d}'.format(restart_num))
        if best_elbo < losses['elbo']:
            best_elbo = losses['elbo']
            save_checkpoint({
                'epoch': epoch,
                'model': model.state_dict()
            }, filename='test_network_best_model')
    print("Finished restart: ", restart_num)