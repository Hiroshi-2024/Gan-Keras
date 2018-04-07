from __future__ import print_function, division
import scipy

from keras.datasets import mnist
from keras_contrib.layers.normalization import InstanceNormalization
from keras.layers import Input, Dense, Reshape, Flatten, Dropout, Concatenate
from keras.layers import BatchNormalization, Activation, ZeroPadding2D, Add
from keras.layers.advanced_activations import LeakyReLU
from keras.layers.convolutional import UpSampling2D, Conv2D
from keras.models import Sequential, Model
from keras.optimizers import Adam
from keras.utils import to_categorical
import datetime
import matplotlib.pyplot as plt
import sys
from data_loader import DataLoader
import numpy as np
import os

class PixelDA():
    def __init__(self):
        # Input shape
        self.img_rows = 32
        self.img_cols = 32
        self.channels = 3
        self.img_shape = (self.img_rows, self.img_cols, self.channels)
        self.num_classes = 10

        # Configure MNIST and MNIST-M data loader
        self.data_loader = DataLoader(img_res=(self.img_rows, self.img_cols))

        # Loss weights
        lambda_adv = 10
        lambda_clf = 1

        # Calculate output shape of D (PatchGAN)
        patch = int(self.img_rows / 2**4)
        self.disc_patch = (patch, patch, 1)

        self.residual_blocks = 6

        # Number of filters in the first layer of G and D
        self.gf = 32
        self.df = 64

        optimizer = Adam(0.0002, 0.5)

        # Build and compile the discriminators
        self.discriminator = self.build_discriminator()
        self.discriminator.compile(loss='mse',
            optimizer=optimizer,
            metrics=['accuracy'])

        # Build and compile the generators
        self.generator = self.build_generator()
        self.generator.compile(loss='binary_crossentropy', optimizer=optimizer)

        self.clf = self.build_classifier()
        self.clf.compile(loss='binary_crossentropy', optimizer=optimizer)

        # Input images from both domains
        img_A = Input(shape=self.img_shape)
        img_B = Input(shape=self.img_shape)

        # Translate images from domain A to domain B
        fake_B = self.generator(img_A)

        # Classify the translated image
        class_pred = self.clf(fake_B)

        # For the combined model we will only train the generators
        self.discriminator.trainable = False

        # Discriminators determines validity of translated images
        valid = self.discriminator(fake_B)

        self.combined = Model(img_A, [valid, class_pred])
        self.combined.compile(loss=['mse', 'categorical_crossentropy'],
                                    loss_weights=[lambda_adv, lambda_clf],
                                    optimizer=optimizer,
                                    metrics=['accuracy'])

    def build_generator(self):
        """Resnet Generator"""

        def residual_block(layer_input):
            """Residual block described in paper"""
            d = Conv2D(64, kernel_size=3, strides=1, padding='same')(layer_input)
            d = BatchNormalization(momentum=0.8)(d)
            d = Activation('relu')(d)
            d = Conv2D(64, kernel_size=3, strides=1, padding='same')(d)
            d = BatchNormalization(momentum=0.8)(d)
            d = Add()([d, layer_input])
            return d

        # Image input
        img = Input(shape=self.img_shape)

        l1 = Conv2D(64, kernel_size=3, padding='same', activation='relu')(img)

        r = residual_block(l1)
        for _ in range(self.residual_blocks - 1):
            r = residual_block(r)

        output_img = Conv2D(self.channels, kernel_size=3, padding='same', activation='tanh')(r)

        return Model(img, output_img)
    #
    # def build_generator(self):
    #     """U-Net Generator"""
    #
    #     def conv2d(layer_input, filters, f_size=4, dropout=0.5):
    #         """Layers used during downsampling"""
    #         d = Conv2D(filters, kernel_size=f_size, strides=2, padding='same')(layer_input)
    #         d = LeakyReLU(alpha=0.2)(d)
    #         d = InstanceNormalization()(d)
    #         # Applies dropout in train and test phase
    #         if dropout:
    #             d = Dropout(dropout)(d, training=True)
    #         return d
    #
    #     def deconv2d(layer_input, skip_input, filters, f_size=4, dropout=0):
    #         """Layers used during upsampling"""
    #         u = UpSampling2D(size=2)(layer_input)
    #         u = Conv2D(filters, kernel_size=f_size, strides=1, padding='same', activation='relu')(u)
    #         u = InstanceNormalization()(u)
    #         # Applies dropout in train and test phase
    #         if dropout:
    #             u = Dropout(dropout)(u, training=True)
    #         u = Concatenate()([u, skip_input])
    #         return u
    #
    #     # Image input
    #     d0 = Input(shape=self.img_shape)
    #
    #     # Downsampling
    #     d1 = conv2d(d0, self.gf)
    #     d2 = conv2d(d1, self.gf*2)
    #     d3 = conv2d(d2, self.gf*4)
    #     d4 = conv2d(d3, self.gf*8)
    #     # Upsampling
    #     u1 = deconv2d(d4, d3, self.gf*4)
    #     u2 = deconv2d(u1, d2, self.gf*2)
    #     u3 = deconv2d(u2, d1, self.gf)
    #
    #     u4 = UpSampling2D(size=2)(u3)
    #     output_img = Conv2D(self.channels, kernel_size=4, strides=1, padding='same', activation='tanh')(u4)
    #
    #     return Model(d0, output_img)

    def build_discriminator(self):

        def d_layer(layer_input, filters, f_size=4, normalization=True):
            """Discriminator layer"""
            d = Conv2D(filters, kernel_size=f_size, strides=2, padding='same')(layer_input)
            d = LeakyReLU(alpha=0.2)(d)
            if normalization:
                d = InstanceNormalization()(d)
            return d

        img = Input(shape=self.img_shape)

        d1 = d_layer(img, self.df, normalization=False)
        d2 = d_layer(d1, self.df*2)
        d3 = d_layer(d2, self.df*4)
        d4 = d_layer(d3, self.df*8)

        validity = Conv2D(1, kernel_size=4, strides=1, padding='same')(d4)

        return Model(img, validity)

    def build_classifier(self):

        def clf_layer(layer_input, filters, f_size=4, normalization=True):
            """Classifier layer"""
            d = Conv2D(filters, kernel_size=f_size, strides=2, padding='same')(layer_input)
            d = LeakyReLU(alpha=0.2)(d)
            if normalization:
                d = InstanceNormalization()(d)
            return d

        img = Input(shape=self.img_shape)

        d1 = clf_layer(img, self.df, normalization=False)
        d2 = clf_layer(d1, self.df*2)
        d3 = clf_layer(d2, self.df*4)
        d4 = clf_layer(d3, self.df*8)
        d5 = clf_layer(d4, self.df*8)

        class_pred = Dense(self.num_classes, activation='softmax')(Flatten()(d5))

        return Model(img, class_pred)

    def train(self, epochs, batch_size=128, save_interval=50):

        half_batch = int(batch_size / 2)

        # Classifier's average accuracy on the 100 latest batches of domain B
        test_accs = []

        for epoch in range(epochs):

            # ---------------------
            #  Train Discriminator
            # ---------------------

            imgs_A, _ = self.data_loader.load_data(domain="A", batch_size=half_batch)
            imgs_B, _ = self.data_loader.load_data(domain="B", batch_size=half_batch)

            # Translate images from domain A to domain B
            fake_B = self.generator.predict(imgs_A)

            valid = np.ones((half_batch,) + self.disc_patch)
            fake = np.zeros((half_batch,) + self.disc_patch)

            # Train the discriminators (original images = real / translated = Fake)
            d_loss_real = self.discriminator.train_on_batch(imgs_B, valid)
            d_loss_fake = self.discriminator.train_on_batch(fake_B, fake)
            d_loss = 0.5 * np.add(d_loss_real, d_loss_fake)


            # --------------------------------
            #  Train Generator and Classifier
            # --------------------------------

            # Sample a batch of images from both domains
            imgs_A, labels_A = self.data_loader.load_data(domain="A", batch_size=batch_size)
            imgs_B, labels_B = self.data_loader.load_data(domain="B", batch_size=batch_size)

            # One-hot encoding of labels
            labels_A = to_categorical(labels_A, num_classes=self.num_classes)

            # The generators want the discriminators to label the translated images as real
            valid = np.ones((batch_size,) + self.disc_patch)

            # Train the generator and classifier
            g_loss = self.combined.train_on_batch(imgs_A, [valid, labels_A])

            # Evaluate classifier on domain B
            pred_B = self.clf.predict(imgs_B)
            test_acc = np.mean(np.argmax(pred_B, axis=1) == labels_B)

            # Add accuracy to list of last 100 accuracy measurements
            test_accs.append(test_acc)
            if len(test_accs) > 100:
                test_accs.pop(0)

            # Plot the progress
            print ( "%d : [D - loss: %.5f, acc: %3d%%], [G - loss: %.5f], [clf - loss: %.5f, acc: %3d%%, test_acc: %3d%% (%3d%%)]" % \
                                            (epoch, d_loss[0], 100*float(d_loss[1]),
                                            g_loss[1], g_loss[2], 100*float(g_loss[-1]),
                                            100*float(test_acc), 100*float(np.mean(test_accs))))


            # If at save interval => save generated image samples
            if epoch % save_interval == 0:
                self.save_imgs(epoch)

    def save_imgs(self, epoch):
        r, c = 2, 5

        imgs_A, _ = self.data_loader.load_data(domain="A", batch_size=5)

        # Translate images to the other domain
        fake_B = self.generator.predict(imgs_A)

        gen_imgs = np.concatenate([imgs_A, fake_B])

        # Rescale images 0 - 1
        gen_imgs = 0.5 * gen_imgs + 0.5

        #titles = ['Original', 'Translated']
        fig, axs = plt.subplots(r, c)
        cnt = 0
        for i in range(r):
            for j in range(c):
                axs[i,j].imshow(gen_imgs[cnt])
                #axs[i, j].set_title(titles[i])
                axs[i,j].axis('off')
                cnt += 1
        fig.savefig("images/%d.png" % (epoch))
        plt.close()


if __name__ == '__main__':
    gan = PixelDA()
    gan.train(epochs=30000, batch_size=32, save_interval=500)
