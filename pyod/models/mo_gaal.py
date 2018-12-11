# -*- coding: utf-8 -*-
"""Grubbs' test for outliers.
Part of the codes are adapted from https://github.com/Cloudy10/loci
"""
# Author: Winston Li <jk_zhengli@hotmail.com>
# License: BSD 2 clause

from __future__ import division
from __future__ import print_function

from keras.layers import Input, Dense
from keras.models import Sequential, Model
from keras.optimizers import SGD
import numpy as np
from collections import defaultdict
import keras
import math
from sklearn.utils import check_array
from sklearn.utils.validation import check_is_fitted

from .base import BaseDetector

class MO_GAAL(BaseDetector):
    """Single-Objective Generative Adversarial Active Learning.
    
    SO-GAAL directly generates informative potential outliers to assist the 
    classifier in describing a boundary that can separate outliers from normal 
    data effectively. Moreover, to prevent the generator from falling into the 
    mode collapsing problem, the network structure of SO-GAAL is expanded from 
    a single generator (SO-GAAL) to multiple generators with different 
    objectives (MO-GAAL) to generate a reasonable reference distribution for 
    the whole dataset.
    Read more in the :cite:`liu2018generative`.
    
    Parameters
    ----------
    contamination : float in (0., 0.5), optional (default=0.1) 
        The amount of contamination of the data set, i.e.
        the proportion of outliers in the data set. Used when fitting to
        define the threshold on the decision function.
    
    stop_epochs : int, default = 20
        The number of epochs of training.
    
    lr_d : float, default = 0.01
        The learn rate of the discrinimator.
    
    lr_g : float, default = 0.0001
        The learn rate of the generator.
    
    decay : int, default = 1e-6
        The decay parameter for SGD.
    
    momentum : float, default = 0.9
        The momentum parameter for SGD.
        
    Attributes
    ----------
    decision_scores\_: numpy array of shape (n_samples,)
        The outlier scores of the training data.
        The higher, the more abnormal. Outliers tend to have higher
        scores. This value is available once the detector is
        fitted.
    
    threshold\_: float
        The threshold is based on ``contamination``. It is the
        ``n_samples * contamination`` most abnormal samples in
        ``decision_scores_``. The threshold is calculated for generating
        binary outlier labels.
    
    labels\_: int, either 0 or 1
        The binary labels of the training data. 0 stands for inliers
        and 1 for outliers/anomalies. It is generated by applying
        ``threshold_`` on ``decision_scores_``.
        
        
    Examples
    --------
    >>> from pyod.models.mo_gaal import MO_GAAL
    >>> from pyod.utils.data import generate_data
    >>> n_train = 50
    >>> n_test = 50
    >>> contamination = 0.1
    >>> X_train, y_train, X_test, y_test = generate_data(
            n_train=n_train, n_test=n_test,
            contamination=contamination, random_state=42)

    >>> clf = MO_GAAL()
    >>> clf.fit(X_train)
    >>> print(clf.decision_scores_)
    """
    
    def __init__(self, k, stop_epochs = 20, lr_d = 0.01, lr_g = 0.0001, 
                 decay = 1e-6, momentum = 0.9, contamination=0.1):
        super(MO_GAAL, self).__init__(contamination=contamination)
        self.k = k
        self.stop_epochs = stop_epochs
        self.lr_d = lr_d
        self.lr_g = lr_g
        self.decay = decay
        self.momentum = momentum
        
    def create_generator(self, latent_size):
        """Cretes the generator of the GAN for a given latent size.
        
        Parameters
        ----------
        latent_size : int
            The size of the latent space of the generator
            
        Returns
        -------
        D : Keras model() object
            Returns a model() object.   
        """
        
        gen = Sequential()
        gen.add(Dense(latent_size, input_dim = latent_size, activation = 'relu', 
                      kernel_initializer = keras.initializers.Identity(gain = 1.0)))
        gen.add(Dense(latent_size, activation = 'relu', 
                      kernel_initializer = keras.initializers.Identity(gain = 1.0)))
        latent = Input(shape = (latent_size, ))
        fake_data = gen(latent)
        return Model(latent, fake_data)
    
    def create_discriminator(self, latent_size, data_size):
        """Cretes the discriminator of the GAN for a given latent size.
        
        Parameters
        ----------
        latent_size : int
            The size of the latent space of the generator.
        
        data_size : int
            Size of the input data.
            
        Returns
        -------
        D : Keras model() object
            Returns a model() object.   
        """
        
        dis = Sequential()
        dis.add(Dense(math.ceil(math.sqrt(data_size)), input_dim = latent_size, 
                      activation = 'relu', 
                      kernel_initializer = keras.initializers.VarianceScaling(scale = 1.0, mode = 'fan_in', distribution = 'normal', seed = None)))
        dis.add(Dense(1, activation = 'sigmoid', 
                      kernel_initializer = keras.initializers.VarianceScaling(scale = 1.0, mode = 'fan_in', distribution = 'normal', seed = None)))
        data = Input(shape = (latent_size, ))
        fake = dis(data)
        return Model(data, fake)
    
    def fit(self, X, y=None):
        """Fit the model using X as training data.
        
        Parameters
        ----------
        X : array, shape (n_samples, n_features)
            Training data.
            
        Returns
        -------
        self : object

        """
        
        X = check_array(X)
        self._set_n_classes(y)
        self.train_history = defaultdict(list)
        names = locals()
        epochs = self.stop_epochs * 3
        stop = 0
        latent_size = X.shape[1]
        data_size = X.shape[0]
        # Create discriminator
        self.discriminator = self.create_discriminator(latent_size, data_size)
        self.discriminator.compile(optimizer = SGD(lr = self.lr_d, decay = self.decay, 
                                              momentum = self.momentum), loss = 'binary_crossentropy')

        # Create k combine models
        for i in range(self.k):
            names['sub_generator' + str(i)] = self.create_generator(latent_size)
            latent = Input(shape = (latent_size, ))
            names['fake' + str(i)] = names['sub_generator' + str(i)](latent)
            self.discriminator.trainable = False
            names['fake' + str(i)] = self.discriminator(names['fake' + str(i)])
            names['combine_model' + str(i)] = Model(latent, names['fake' + str(i)])
            names['combine_model' + str(i)].compile(optimizer=SGD(lr = self.lr_g, 
                  decay = self.decay, momentum = self.momentum), loss='binary_crossentropy')

        # Start iteration
        for epoch in range(epochs):
            print('Epoch {} of {}'.format(epoch + 1, epochs))
            batch_size = min(500, data_size)
            num_batches = int(data_size / batch_size)

            for index in range(num_batches):
                print('\nTesting for epoch {} index {}:'.format(epoch + 1, index + 1))

                # Generate noise
                noise_size = batch_size
                noise = np.random.uniform(0, 1, (int(noise_size), latent_size))

                # Get training data
                data_batch = X[index * batch_size: (index + 1) * batch_size]

                # Generate potential outliers
                block = ((1 + self.k) * self.k) // 2
                for i in range(self.k):
                    if i != (self.k - 1):
                        noise_start = int((((self.k + (self.k - i + 1)) * i) / 2) * (noise_size // block))
                        noise_end = int((((self.k + (self.k - i)) * (i + 1)) / 2) * (noise_size // block))
                        names['noise' + str(i)] = noise[noise_start:noise_end ]
                        names['generated_data' + str(i)] = names['sub_generator' + str(i)].predict(names['noise' + str(i)], verbose=0)
                    else:
                        noise_start = int((((self.k + (self.k - i + 1)) * i) / 2) * (noise_size // block))
                        names['noise' + str(i)] = noise[noise_start:noise_size]
                        names['generated_data' + str(i)] = names['sub_generator' + str(i)].predict(names['noise' + str(i)], verbose=0)

                # Concatenate real data to generated data
                for i in range(self.k):
                    if i == 0:
                        x = np.concatenate((data_batch, names['generated_data' + str(i)]))
                    else:
                        x = np.concatenate((x, names['generated_data' + str(i)]))
                y = np.array([1] * batch_size + [0] * int(noise_size))

                # Train discriminator
                discriminator_loss = self.discriminator.train_on_batch(x, y)
                self.train_history['discriminator_loss'].append(discriminator_loss)

                # Get the target value of sub-generator
                pred_scores = self.discriminator.predict(X)
                
                for i in range(self.k):
                    names['T' + str(i)] = np.percentile(pred_scores, i/self.k*100)
                    names['trick' + str(i)] = np.array([float(names['T' + str(i)])] * noise_size)

                # Train generator
                noise = np.random.uniform(0, 1, (int(noise_size), latent_size))
                if stop == 0:
                    for i in range(self.k):
                        names['sub_generator' + str(i) + '_loss'] = names['combine_model' + str(i)].train_on_batch(noise, names['trick' + str(i)])
                        self.train_history['sub_generator{}_loss'.format(i)].append(names['sub_generator' + str(i) + '_loss'])
                else:
                    for i in range(self.k):
                        names['sub_generator' + str(i) + '_loss'] = names['combine_model' + str(i)].evaluate(noise, names['trick' + str(i)])
                        self.train_history['sub_generator{}_loss'.format(i)].append(names['sub_generator' + str(i) + '_loss'])

                generator_loss = 0
                for i in range(self.k):
                    generator_loss = generator_loss + names['sub_generator' + str(i) + '_loss']
                generator_loss = generator_loss / self.k
                self.train_history['generator_loss'].append(generator_loss)

                # Stop training generator
                if epoch +1  > self.stop_epochs:
                    stop = 1

            # Detection result
            self.decision_scores_ = self.discriminator.predict(X)
            self._process_decision_scores()
            
    def decision_function(self, X):
        check_is_fitted(self, ['discriminator'])
        X = check_array(X)
        pred_scores = self.discriminator.predict(X)
        return pred_scores