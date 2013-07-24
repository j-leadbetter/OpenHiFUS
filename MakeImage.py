# import PyOpenCL and Numpy. An OpenCL-enabled GPU is not required,
# OpenCL kernels can be compiled on most CPUs thanks to the Intel SDK for OpenCL
# or the AMD APP SDK.
import pyopencl as cl
import numpy as np
from matplotlib import pyplot as plt
import time





# create an OpenCL context
platform = cl.get_platforms()
my_gpu_devices = platform[0].get_devices(device_type=cl.device_type.GPU)
ctx = cl.Context(devices=my_gpu_devices)
queue = cl.CommandQueue(ctx)


# create the kernel input

#Blank buffers for testing for now
Angles = np.arange(-35,35)
Focals = np.array([5,7,9], dtype = np.float32)
Elems  = np.arange(64)

numBuffers  = (64 / 2) * 2
RecPerBuff = len(Angles) * len(Focals)
recordCnt = len(Angles) * len(Focals)
ChPerRec = 2
sampleCnt = 320*15

lenBuffers = recordCnt * sampleCnt *ChPerRec

RandBuf = np.array(np.random.randint(0,2**16, (numBuffers, lenBuffers)) , dtype=np.uint16)

# kernel output placeholder
img = np.empty((sampleCnt/15,len(Angles)),dtype = np.uint16)

img[0,:] = [ 0 for i in img[0,:]]


'''
# create context buffers for a and b arrays
# for a (input), we need to specify that this buffer should be populated from a
data_buf = cl.Buffer(ctx, cl.mem_flags.READ_ONLY | cl.mem_flags.COPY_HOST_PTR,
                    hostbuf=RandBuf)
# for b (output), we just allocate an empty buffer
img_buf = cl.Buffer(ctx, cl.mem_flags.WRITE_ONLY, img.nbytes)

# OpenCL kernel code
code = """
__kernel void makepix(__global int* data, __global int* img) {
    int i = get_global_id(0);
    int jsize = get_global_size(1);
    int j = get_global_id(1);
    int k = get_global_id(2);
    int wrkidx = i*jsize+j;
    printf("block %d ", i);
    img[wrkidx] = data[wrkidx];
}
"""

# compile the kernel
prg = cl.Program(ctx, code).build()

# launch the kernel
# a.shape = (10,) - Basically gives globalID
thdsize = img.shape
#event = prg.makepix(queue, thdsize, data_buf, img_buf)
event = prg.makepix(queue, (30,2), data_buf, img_buf)
event.wait()

# copy the output from the context to the Python process
cl.enqueue_copy(queue, img, img_buf)


plt.imshow(img)
plt.show()


'''





def makepix(data, RecordCnt = 71, SampleCne = 320*5):
    RecordCnt =
    return None
