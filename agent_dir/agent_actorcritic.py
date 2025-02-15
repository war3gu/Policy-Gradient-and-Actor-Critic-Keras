from agent_dir.agent import Agent
import numpy as np
import scipy
import random

import os
import keras
import tensorflow as tf
from keras.models import Sequential,load_model, Model
from keras.layers import Dense, Dropout, Flatten, Multiply
from keras.layers import Conv2D, MaxPooling2D, Input, Lambda
from keras.optimizers import Adam, Adamax, RMSprop
from keras import backend as K

MAX_TIMESTEP = 1000
MAX_EP = 3000
from keras.backend.tensorflow_backend import set_session
config = tf.ConfigProto()
config.gpu_options.per_process_gpu_memory_fraction = 0.1
set_session(tf.Session(config=config))

random.seed(2)
np.random.seed(2)
tf.set_random_seed(2)

# ref : https://github.com/MorvanZhou/Reinforcement-learning-with-tensorflow/

def categorical_crossentropy(target, output):
    _epsilon =  tf.convert_to_tensor(10e-8, dtype=output.dtype.base_dtype)
    output = tf.clip_by_value(output, _epsilon, 1. - _epsilon)
    return (- target * tf.log(output))


class Agent_ActorCritic(Agent):
    def __init__(self, env, args):
        super(Agent_ActorCritic,self).__init__(env)

        self.log_path = './actor_critic.log'

        self.env = env
        self.actions_avialbe = env.action_space.n
        self.feature_dim = env.observation_space.shape[0]
        self.t = 0
        self.prev_x = None
        self.actor_learning_rate  = 1e-3
        self.critic_learning_rate = 1e-3
        self.gamma = 0.9

        self.dummy_act_picked = np.zeros((1,self.actions_avialbe))

        self.actor = self.buildActor()

        self.critic = self.buildCritic()



    def buildActor(self):
        # Actor
        input_frame  = Input(shape=(self.feature_dim,))
        act_picked = Input(shape=(self.actions_avialbe,))
        hidden_f = Dense(20,activation='relu')(input_frame)

        act_prob = Dense(self.actions_avialbe,activation='softmax')(hidden_f)
        selected_act_prob = Multiply()([act_prob,act_picked])

        #output_shape参数可以省略
        #Lambda可以看作一个Layer，以下代码可以看作把输入的最后一维求和，并保持维数
        selected_act_prob = Lambda(lambda x:K.sum(x, axis=-1, keepdims=True),output_shape=(1,))(selected_act_prob)
        #selected_act_prob = Lambda(lambda x: K.sum(x, axis=-1, keepdims=True))(selected_act_prob)

        #输出act_prob是在策略sample的时候要用到，selected_act_prob是在train的时候要用到，这个才是真正的误差
        model = Model(inputs=[input_frame,act_picked], outputs=[act_prob, selected_act_prob])
        #model = Model(inputs=[input_frame, act_picked], outputs=[selected_act_prob])

        opt = Adam(lr=self.actor_learning_rate)
        #loss_weights是2个输出的loss的组合权重，模型训练目标是一个总的loss
        #categorical_crossentropy是自定义的loss函数，参数不用是one_hot,与系统定义的"categorical_crossentropy"有差别
        #actor的loss函数的形式为-Adv*log(selected_act_prob),与交叉熵的形式有点像，但是Adv和selected_act_prob都不用是分布
        model.compile(loss=['mse',categorical_crossentropy], loss_weights=[0.0,1.0],optimizer=opt)
        #model.compile(loss=['mse', "categorical_crossentropy"], loss_weights=[0.0, 1.0], optimizer=opt)
        #model.compile(loss=[categorical_crossentropy], loss_weights=[1.0], optimizer=opt)
        return model

    def buildCritic(self):
        # Critic
        model = Sequential()
        model.add(Dense(20,activation='relu',input_shape=(self.feature_dim,)))
        model.add(Dense(1))

        opt = Adam(lr=self.critic_learning_rate)
        model.compile(loss='mse', optimizer=opt)
        return model

    def init_game_setting(self):
        self.prev_x = None


    def train(self):
        # Init
        log = open(self.log_path,'w')
        log.write('reward,avg_reward\n')
        batch_size = 1 
        frames, prob_actions, dlogps, drs =[], [], [], []
        tr_x, tr_y = [],[]
        reward_record = []
        avg_reward = []
        reward_sum = 0
        ep_number = 0
        ep_step = 0 
        #explore_rate = 0
        observation = self.env.reset()
        # Training progress
        while True:
            self.env.env.render()

            ax = np.arange(self.actions_avialbe)
            #一张图片就是一个batch，所以需要扩展出一个表示图片数量的batch维度，这个维度的shape值为1
            cc = np.expand_dims(observation,axis=0)
            dd = self.actor.predict([cc, self.dummy_act_picked])
            px = dd[0].flatten()

            act = np.random.choice(a=ax, p=px)

            act_one_hot = np.zeros((1,self.actions_avialbe))
            act_one_hot[0,act]=1.0
            next_observation, reward, done, info = self.env.step(act)
            if done: reward = -20
            
            reward_sum += reward
            predict_reward = self.critic.predict(np.expand_dims(observation,axis=0))
            predict_next_reward = self.critic.predict(np.expand_dims(next_observation,axis=0))

            td_target = np.expand_dims(reward,axis=0) + self.gamma*predict_next_reward
            td_error = td_target - predict_reward

            self.critic.train_on_batch(np.expand_dims(observation,axis=0),td_target)
            self.actor.train_on_batch([np.expand_dims(observation,axis=0),act_one_hot],[self.dummy_act_picked,td_error])

            observation = next_observation

            self.t += 1
            ep_step += 1

            if done or ep_step>MAX_TIMESTEP:
                ep_number += 1
                
                avg_reward.append(float(reward_sum))
                if len(avg_reward)>30: avg_reward.pop(0)

                print('EPISODE: {0:6d} / TIMESTEP: {1:8d} / REWARD: {2:5d} / AVG_REWARD: {3:2.3f} '.format(
                            ep_number, self.t, int(reward_sum), np.mean(avg_reward)))
                print('{:.4f},{:.4f}'.format(reward_sum,np.mean(avg_reward)),end='\n',file=log,flush=True)

                observation = self.env.reset()
                reward_sum = 0.0
                ep_step = 0


            if ep_number >= MAX_EP:
                self.actor.save('actor.h5')
                self.critic.save('critictor.h5')
                break



    def make_action(self, observation, test=True):
        """
        Input:
            observation: np.array
                current RGB screen of game, shape: (210, 160, 3)

        Return:
            action: int
                the predicted action from trained model
        """
        pass