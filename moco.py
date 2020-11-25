import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim

import torchvision.datasets as datasets

import numpy as np

import os

import time
import math
from torchvision.models.resnet import conv3x3

class BasicBlock(nn.Module):
    def __init__(self, inplanes, planes, norm_layer, stride=1, downsample=None):
        super(BasicBlock, self).__init__()
        self.downsample = downsample
        self.stride = stride
        
        self.bn1 = norm_layer(inplanes)
        self.relu1 = nn.ReLU(inplace=True)
        self.conv1 = conv3x3(inplanes, planes, stride)
        
        self.bn2 = norm_layer(planes)
        self.relu2 = nn.ReLU(inplace=True)
        self.conv2 = conv3x3(planes, planes)

    def forward(self, x):
        residual = x 
        residual = self.bn1(residual)
        residual = self.relu1(residual)
        residual = self.conv1(residual)

        residual = self.bn2(residual)
        residual = self.relu2(residual)
        residual = self.conv2(residual)

        if self.downsample is not None:
            x = self.downsample(x)
        return x + residual

class Downsample(nn.Module):
    def __init__(self, nIn, nOut, stride):
        super(Downsample, self).__init__()
        self.avg = nn.AvgPool2d(stride)
        assert nOut % nIn == 0
        self.expand_ratio = nOut // nIn

    def forward(self, x):
        x = self.avg(x)
        return torch.cat([x] + [x.mul(0)] * (self.expand_ratio - 1), 1)

class ResNetCifar(nn.Module):
    def __init__(self, depth, width=1, classes=10, channels=3, norm_layer=nn.BatchNorm2d):
        assert (depth - 2) % 6 == 0         # depth is 6N+2
        self.N = (depth - 2) // 6
        super(ResNetCifar, self).__init__()

        # Following the Wide ResNet convention, we fix the very first convolution
        self.conv1 = nn.Conv2d(channels, 16, kernel_size=3, stride=1, padding=1, bias=False)
        self.inplanes = 16
        self.layer1 = self._make_layer(norm_layer, 16 * width)
        self.layer2 = self._make_layer(norm_layer, 32 * width, stride=2)
        self.layer3 = self._make_layer(norm_layer, 64 * width, stride=2)
        self.bn = norm_layer(64 * width)
        self.relu = nn.ReLU(inplace=True)
        self.avgpool = nn.AvgPool2d(8)

        # Initialization
        for m in self.modules():
            if isinstance(m, nn.Conv2d):
                n = m.kernel_size[0] * m.kernel_size[1] * m.out_channels
                m.weight.data.normal_(0, math.sqrt(2. / n))
                
    def _make_layer(self, norm_layer, planes, stride=1):
        downsample = None
        if stride != 1 or self.inplanes != planes:
            downsample = Downsample(self.inplanes, planes, stride)
        layers = [BasicBlock(self.inplanes, planes, norm_layer, stride, downsample)]
        self.inplanes = planes
        for i in range(self.N - 1):
            layers.append(BasicBlock(self.inplanes, planes, norm_layer))
        return nn.Sequential(*layers)

    def forward(self, x):
        x = self.conv1(x)
        x = self.layer1(x)
        x = self.layer2(x)
        x = self.layer3(x)
        x = self.bn(x)
        x = self.relu(x)
        x = self.avgpool(x)
        x = x.view(x.size(0), -1)
        return x

    
class Normalize(nn.Module):

    def __init__(self, power=2):
        super(Normalize, self).__init__()
        self.power = power

    def forward(self, x):
        norm = x.pow(self.power).sum(1, keepdim=True).pow(1. / self.power)
        out = x.div(norm)
        return out
    

class SimCLRHead(nn.Module):
    def __init__(self, width, emb_dim):
        super(SimCLRHead, self).__init__()
        
        ### IMPLEMENTATION 1-1 ###
        ### 1. Linear layer (64 * width -> 64 * width)
        ### 2. ReLU
        ### 3. Linear layer (64 * width -> emb_dim)
        ### 4. Normalization layer (Normalize module above)
        self.fc1 = nn.Linear(64*width,64*width)
        self.relu = nn.ReLU(inplace=True)
        self.fc2 = nn.Linear(64*width,emb_dim)
        self.norm = Normalize()
        ### IMPLEMENTATION ENDS HERE ###
        
    def forward(self, x):
        
        ### IMPLEMENTATION 1-1 ###
        ### Design a proper forward function
        x = self.fc1(x)
        x = self.relu(x)
        x = self.fc2(x)
        x = self.norm(x)
        ### IMPLEMENTATION ENDS HERE ###
        return x
    

class SimCLRNet(nn.Module):
    def __init__(self, depth, width=1, num_classes=10, emb_dim=32):
        super(SimCLRNet, self).__init__()
        
        self.num_classes = num_classes
        
        self.feat = ResNetCifar(depth=depth, width=width, classes=num_classes)
        
        ### IMPLEMENTATION 1-2 ###
        ### 1. A projection head (SimCLRHead module above)
        self.head = SimCLRHead(width,emb_dim)
        
        ### 2. A linear classifier (64 * width -> num_classes)
        self.classifier = nn.Linear(64*width,num_classes)
        
        ### 3. Normalization layer for conv feature normalization (Normalize module above)
        self.norm = Normalize()
        
        ### IMPLEMENTATION ENDS HERE ###
    
    def forward(self, x, norm_feat=False):
        
        ### IMPLEMENTATION 1-2 ###
        ### Your module must return
        ### 1. Conv feature (feat) - when norm_feat is true, apply L2 normalization
        ### 2. Projected embedding (emb)
        ### 3. Logit vector by the linear classifier (logit)
        feat = self.feat(x)
        if norm_feat==True:
          feat=self.norm(feat)
        emb = self.head(feat)
        logit = self.classifier(feat)
        ### IMPLEMENTATION ENDS HERE ###
        return feat, emb, logit

class DuplicatedCompose(object):
    def __init__(self, transforms):
        self.transforms = transforms

    def __call__(self, img):
        img1 = img.copy()
        img2 = img.copy()
        for t in self.transforms:
            img1 = t(img1)
            img2 = t(img2)
        return img1, img2

import cv2
cv2.setNumThreads(0)

class GaussianBlur(object):
    # Implements Gaussian blur as described in the SimCLR paper
    def __init__(self, kernel_size, min=0.1, max=2.0):
        self.min = min
        self.max = max
        # kernel size is set to be 10% of the image height/width
        self.kernel_size = kernel_size
        
        if self.kernel_size % 2 == 0:
            self.kernel_size += 1

    def __call__(self, sample):
        sample = np.array(sample)

        # blur the image with a 50% chance
        prob = np.random.random_sample()

        if prob < 0.5:
            sigma = (self.max - self.min) * np.random.random_sample() + self.min
            sample = cv2.GaussianBlur(sample, (self.kernel_size, self.kernel_size), sigma)

        return sample

import torchvision.transforms as transforms

img_size = (32, 32)

color_jitter = transforms.ColorJitter(0.8, 0.8, 0.8, 0.2)

train_transform = DuplicatedCompose([
    ### IMPLEMENTATION 2-1 ###
    ### 1. Random resized crop w/ final size of (32, 32)
    ### 2. Random horizontal flip w/ p=0.5
    ### 3. Randomly apply the pre-defined color jittering w/ p=0.8
    ### 4. Random gray scale w/ p=0.2
    ### 5. Gaussian blur w/ kernel size of 1/10 of the image width or height (32)
    transforms.RandomResizedCrop(size=(32,32)),
    transforms.RandomHorizontalFlip(p=0.5),
    transforms.RandomApply([color_jitter],p=0.8),
    transforms.RandomGrayscale(p=0.2),
    GaussianBlur(kernel_size=int(0.1*32)),
    ### IMPLEMENTATION ENDS HERE ###
    transforms.ToTensor(),
])

from torch.utils.data import DataLoader

train_dataset = datasets.CIFAR10(root='../../../home_klimt/dohyun.kim/',
                                 train=True,
                                 download=True,
                                 transform=train_transform
                                )

train_loader = DataLoader(train_dataset,
                          batch_size=256,
                          num_workers=4,
                          shuffle=True,
                          drop_last=True
                         )


class NTXentLoss(torch.nn.Module):

    def __init__(self, batch_size, temperature, use_cosine_similarity):
        super(NTXentLoss, self).__init__()
        self.batch_size = batch_size
        self.temperature = temperature
        self.softmax = torch.nn.Softmax(dim=-1)
        self.mask_samples_from_same_repr = self._get_correlated_mask().type(torch.bool)
        self.similarity_function = self._get_similarity_function(use_cosine_similarity)
        self.criterion = torch.nn.CrossEntropyLoss(reduction="sum")

    def _get_similarity_function(self, use_cosine_similarity):
        if use_cosine_similarity:
            self._cosine_similarity = torch.nn.CosineSimilarity(dim=-1)
            return self._cosine_simililarity
        else:
            return self._dot_simililarity

    def _get_correlated_mask(self):
        diag = np.eye(2 * self.batch_size)
        l1 = np.eye((2 * self.batch_size), 2 * self.batch_size, k=-self.batch_size)
        l2 = np.eye((2 * self.batch_size), 2 * self.batch_size, k=self.batch_size)
        mask = torch.from_numpy((diag + l1 + l2))
        mask = (1 - mask).type(torch.bool)
        return mask.cuda()

    @staticmethod
    def _dot_simililarity(x, y):
        v = torch.tensordot(x.unsqueeze(1), y.T.unsqueeze(0), dims=2)
        # x shape: (N, 1, C)
        # y shape: (1, C, 2N)
        # v shape: (N, 2N)
        return v

    def _cosine_simililarity(self, x, y):
        # x shape: (N, 1, C)
        # y shape: (1, 2N, C)
        # v shape: (N, 2N)
        v = self._cosine_similarity(x.unsqueeze(1), y.unsqueeze(0))
        return v

    def forward(self, zis, zjs):
        representations = torch.cat([zjs, zis], dim=0)

        similarity_matrix = self.similarity_function(representations, representations)

        # filter out the scores from the positive samples
        l_pos = torch.diag(similarity_matrix, self.batch_size)
        r_pos = torch.diag(similarity_matrix, -self.batch_size)
        positives = torch.cat([l_pos, r_pos]).view(2 * self.batch_size, 1)

        negatives = similarity_matrix[self.mask_samples_from_same_repr].view(2 * self.batch_size, -1)

        logits = torch.cat((positives, negatives), dim=1)
        logits = logits / self.temperature

        labels = torch.zeros(2 * self.batch_size).cuda().long()
        loss = self.criterion(logits, labels)

        return loss / (2 * self.batch_size)

from torch.optim.optimizer import Optimizer, required

class SGD_with_lars(Optimizer):
    r"""Implements stochastic gradient descent (optionally with momentum).
    """

    def __init__(self, params, lr=required, momentum=0, weight_decay=0, trust_coef=1.): # need to add trust coef
        if lr is not required and lr < 0.0:
            raise ValueError("Invalid learning rate: {}".format(lr))
        if momentum < 0.0:
            raise ValueError("Invalid momentum value: {}".format(momentum))
        if weight_decay < 0.0:
            raise ValueError("Invalid weight_decay value: {}".format(weight_decay))
        if trust_coef < 0.0:
            raise ValueError("Invalid trust_coef value: {}".format(trust_coef))

        defaults = dict(lr=lr, momentum=momentum, weight_decay=weight_decay, trust_coef=trust_coef)

        super(SGD_with_lars, self).__init__(params, defaults)

    def __setstate__(self, state):
        super(SGD_with_lars, self).__setstate__(state)

    def step(self, closure=None):
        """Performs a single optimization step.
        Arguments:
            closure (callable, optional): A closure that reevaluates the model
                and returns the loss.
        """
        loss = None
        if closure is not None:
            loss = closure()

        for group in self.param_groups:
            weight_decay = group['weight_decay']
            momentum = group['momentum']
            trust_coef = group['trust_coef']
            global_lr = group['lr']

            for p in group['params']:
                if p.grad is None:
                    continue
                d_p = p.grad.data

                p_norm = torch.norm(p.data, p=2)
                d_p_norm = torch.norm(d_p, p=2).add_(momentum, p_norm)
                lr = torch.div(p_norm, d_p_norm).mul_(trust_coef)

                lr.mul_(global_lr)

                if weight_decay != 0:
                    d_p.add_(weight_decay, p.data)

                d_p.mul_(lr)

                if momentum != 0:
                    param_state = self.state[p]
                    if 'momentum_buffer' not in param_state:
                        buf = param_state['momentum_buffer'] = torch.clone(d_p).detach()
                    else:
                        buf = param_state['momentum_buffer']
                        buf.mul_(momentum).add_(d_p)
                    d_p = buf

                p.data.add_(-1, d_p)

        return loss

def train(net, loader):
    
    loss_fn = NTXentLoss(batch_size=256, temperature=0.05, use_cosine_similarity=True)
    
    ### IMPLEMENTATION 4-2 ###
    ### 1. Use SGD_with_lars with
    ### lr = 0.1 * batch_size / 256
    ### momentum = 0.9
    ### weight_decay = 1e-6
    optimizer = SGD_with_lars(net.parameters(), lr=0.1, momentum = 0.9, weight_decay = 1e-6)
    
    from warmup_scheduler import GradualWarmupScheduler
    ### 2. Use GradualWarmupScheduler with
    ### multiplier = 1
    ### total_epoch = 1/10 of total epochs
    ### after_scheduler = optim.lr_scheduler.CosineAnnealingLR
    scheduler = GradualWarmupScheduler(optimizer, multiplier=1, total_epoch=20, after_scheduler=optim.lr_scheduler.CosineAnnealingLR(optimizer,T_max=180))
    
    train_start = time.time()
    
    for epoch in range(1, 200 + 1):
        train_loss = 0
        net.train()
        epoch_start = time.time()
        for idx, (data, target) in enumerate(loader):
            optimizer.zero_grad()
            
            ### 3. data variable contains two augmented images
            ### -1. send them to your GPU by calling .cuda()
            ### -2. forward each of them to net
            ### -3. compute the InfoNCE loss
            
            dat1 = data[0].cuda()
            dat2 = data[1].cuda()
            #print(dat1.shape)
            dat1 = net(dat1)[1]
            dat2 = net(dat2)[1]
           # print(dat1.dtype)
            loss = loss_fn(dat1, dat2)
            ### IMPLEMENTATION ENDS HERE ###
            
            train_loss += loss.item()
            
            loss.backward()
            optimizer.step()
            
        train_loss /= (idx + 1)
        scheduler.step()
        
        epoch_time = time.time() - epoch_start
        print("Epoch\t", epoch, 
              "\tLoss\t", train_loss, 
              "\tTime\t", epoch_time,
             )
        
    elapsed_train_time = time.time() - train_start
    print('Finished training. Train time was:', elapsed_train_time)

GPU_NUM = '0'
os.environ["CUDA_VISIBLE_DEVICES"] = GPU_NUM

net = SimCLRNet(26, 1, 10, 32)

net.cuda()
train(net, train_loader)
torch.save(net.state_dict(), '../../../home_klimt/dohyun.kim/pretrained.pt')

net = SimCLRNet(26, 1, 10, 32)
net.load_state_dict(torch.load('../../../home_klimt/dohyun.kim/pretrained.pt'))
net.eval()
net.cuda()
def train2(net, train_loader, test_loader):
    
    loss_fn = nn.CrossEntropyLoss()
  
    optimizer = optim.Adam(filter(lambda p: p.requires_grad, net.parameters()), lr=1e-3)
    from warmup_scheduler import GradualWarmupScheduler
    scheduler = GradualWarmupScheduler(optimizer, multiplier=1, total_epoch=20, after_scheduler=optim.lr_scheduler.CosineAnnealingLR(optimizer,T_max=80))
    
    train_start = time.time()
    
    for epoch in range(1, 100 + 1):
        
        train_loss = 0
        net.train()
        
        epoch_start = time.time()
        for idx, (data, target) in enumerate(train_loader):
            optimizer.zero_grad()
            data = data.cuda()
            target = target.cuda()
            data = net(data)[2]
            loss = loss_fn(data, target)
            ### IMPLEMENTATION ENDS HERE ###
            
            train_loss += loss.item()
            
            loss.backward()
            optimizer.step()
            
        train_loss /= (idx + 1)
        scheduler.step()
        
        epoch_time = time.time() - epoch_start
       # print("Epoch\t", epoch, 
       #       "\tLoss\t", train_loss, 
       #       "\tTime\t", epoch_time,
       #      )
        
        if epoch % 10 == 0:
          net.eval()
          total = 0.0
          correct = 0.0
          for test_data in test_loader:
            images, labels = test_data
            images = images.cuda()
            labels = labels.cuda()
            outputs = net(images)[2]
            _, predicted = torch.max(outputs.data, 1)
            total += labels.size(0)
            correct += (predicted == labels).sum().item()

          print("Epoch\t",epoch,"\tTest accuracy\t",correct/total*100)

    elapsed_train_time = time.time() - train_start
    print('Finished training. Train time was:', elapsed_train_time)

transform2 = transforms.Compose([
    transforms.ToTensor(),
])
cnt=0
for p in net.feat.parameters():
    p.requires_grad = False
    cnt = cnt + 1
print(cnt)

train_dataset2 = datasets.CIFAR10(root='.',
                                 train=True,
                                 download=True,
                                 transform=transform2
                                )

test_dataset2 = datasets.CIFAR10(root='.',
                                 train=False,
                                 download=True,
                                 transform=transform2
                                )

train_loader2 = DataLoader(train_dataset2,
                          batch_size=256,
                          num_workers=4,
                          shuffle=True,
                          drop_last=True
                         )

test_loader2 = DataLoader(test_dataset2,
                          batch_size=256,
                          num_workers=4,
                          shuffle=True,
                          drop_last=True
                         )

train2(net, train_loader2, test_loader2)
