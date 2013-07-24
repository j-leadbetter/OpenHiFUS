# -*- coding: utf-8 -*-
"""
Created on Tue Jul 23 14:27:28 2013

@author: Michael

Makes a pointer library to tell where to start reading data from in order to generate images
"""
import numpy as np
from matplotlib import pyplot as plt
import time



#Focal = [6e-3, 8e-3, 12e-3]
Focal = [8e-3]
Angle = range(-35,35+1)
#Angle = [30]
Element = range(64)
c = 1.54e3
ep = 3.8e-5


# Alazar Aquisitions Parameters
SampleCnt = 320*5
RecordCnt = len(Focal) * len(Angle)

Offset = 500.0e-9
SamplingRate = 500e6 # 500 Mega Samples Per Second
dt = 1.0/SamplingRate


Buffer = np.random.randint(2**12, size=(32, SampleCnt*RecordCnt))

if not (len(Buffer[1,:])/float(RecordCnt)==SampleCnt):
    raise Exception('Check your values! RecordCnt * SampleCnt should give len(Buffer)' )


# Delay variables for loop
Dela = []
DelOff = np.zeros((RecordCnt,64),dtype=int)

t0 = time.time()
for ele in Element:
    Temp = []
    for foc in Focal:
        for ang in Angle:

            Delay = (foc-np.sqrt((foc*np.sin(np.radians(90+ang)))**2+(foc*np.cos(np.radians(90+ang))-(32-ele)*ep)**2))/(c)
            Temp.append(Delay/dt)
            print int(Delay/dt)
            Dela.append(Delay*1e9)
    DelOff[:,ele] = Temp


plt.figure(1)
plt.axis([800,-800,65,-1])
plt.title('Delay profile')
plt.xlabel(r'Delay time [$ns$]')
plt.ylabel('Element number')

for i in range(len(Dela)/64):
    plt.plot(Dela[i*64:(i+1)*64],Element,'.-')

plt.show()


