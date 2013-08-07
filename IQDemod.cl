// Global definitions
#define SAMPLE_RATE_SETTING 500.0E+06
#define SAMPLE_RATE_ID SAMPLE_RATE_500MSPS
// Data processing constants
#define IQ_DELAY   5 // Should be 1/4 of samplerate for 1 wavelength
#define K_CARD	1.2210012210012e-05 // = 800 /(16*4095)
#define R_CARD  0.3987300000000
#define NOISE_FLOOR 0.40000E-03 //mV
#define NOISE_DB  -60.000000000

#pragma OPENCL EXTENSION cl_khr_fp64 : enable


__kernel void iqDemodAvg(__constant unsigned short *buffer, __global double *dataOut, __constant double *gain, __constant int* OCLParams, __constant int* DAQParams)
{
    //Function demodulates RF data to A mode scan lines
    int i, j, k;
    int iIndex, qIndex;
    unsigned long int iData32, qData32;
    double iData, qData, iq2Data, logData;

    i = get_global_id(0);
    //printf("y%d ", i);
    iIndex = i*OCLParams[3]; // Decimate
    qIndex = i*OCLParams[3] + IQ_DELAY;

    //Average over specified number of buffers
    iData32 = 0;
    qData32 = 0;
    for(j=0; j < OCLParams[1]; j++) // NumAverage
    {
        k = (DAQParams[0]+OCLParams[0]-j) % DAQParams[0]; // BufferIndex, BufferCount
        // C99 Modulo of a neg int is negative. Thus I add the mod to always be positive. 

        iData32 += buffer[iIndex + DAQParams[1] * k]; // BufferLength
        qData32 += buffer[qIndex + DAQParams[1] * k];
    }
    iData32 /= OCLParams[1]; // NumAverage
    qData32 /= OCLParams[1];

    iData = (double)iData32*K_CARD - R_CARD;
    qData = (double)qData32*K_CARD - R_CARD;

    if (OCLParams[2] == 1)
    {
        iData *= gain[iIndex % DAQParams[3]]; // SamplesPerRecord
        qData *= gain[qIndex % DAQParams[3]];
    }

    iq2Data = (iData * iData + qData * qData);
    logData = 10*log10(iq2Data) - NOISE_DB;

    dataOut[i] = max(logData, 0.0);



}