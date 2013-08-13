// Data processing constants
#define IQ_DELAY 5
#define K_CARD	1.2210012210012e-05
#define R_CARD  0.3987300000000
#define NOISE_DB  -60.000000000

#pragma OPENCL EXTENSION cl_khr_fp64 : enable


__kernel void iqDemodAvg(__constant unsigned short *buffer, __global double *dataOut, __constant double *gain, __constant int* OCLParams, __constant int* DAQParams)
{
    //Function demodulates RF data to A mode scan lines
    
    int i, j, k;
    int iIndex, qIndex;
    unsigned long int iData32, qData32;
    double iData, qData, iq2Data, logData;
    
    int bufIndex, numAverage, useGain, decimate;
    int numBuffers, bufLength, recLength;
    
    
    //Assign arguments to local vars
    bufIndex   = OCLParams[0];
    numAverage = OCLParams[1];
    useGain    = OCLParams[2];
    decimate   = OCLParams[3];
    
    numBuffers = DAQParams[0];
    bufLength  = DAQParams[1];
    recLength  = DAQParams[3];

    i = get_global_id(0);
    
    iIndex = i*decimate;
    qIndex = i*decimate + IQ_DELAY;

    //Average over specified number of buffers
    iData32 = 0;
    qData32 = 0;
    for(j=0; j < numAverage; j++)
    {
        // C99 Modulo of a neg int is negative. 
        // Fix is to work on range of [numBuf:numBuf*2] 
        k = (numBuffers+bufIndex-j) % numBuffers;
        

        iData32 += buffer[iIndex + k*bufLength];
        qData32 += buffer[qIndex + k*bufLength];
    }
    iData32 /= numAverage;
    qData32 /= numAverage;

    iData = (double)iData32*K_CARD - R_CARD;
    qData = (double)qData32*K_CARD - R_CARD;

    if (useGain == 1)
    {
        iData *= gain[iIndex % recLength];
        qData *= gain[qIndex % recLength];
    }

    iq2Data = (iData * iData + qData * qData);
    logData = 10*log10(iq2Data) - NOISE_DB;

    dataOut[i] = max(logData, 0.0);

}