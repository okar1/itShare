import struct, serial, usb
import time

class ItPlanar():

    usbVid=0x2226
    usbPid=0x0010

    # wait for signal lock and ber measure for specified time.
    berMeasureTimeoutSec=9
    # repeat ber polling with specified interval until got a value or timeout
    berMeasureIntervalSec=0.5
    # max and min ber values device can measure. Return 0 if got value outside this interval
    maxBerAllowed=5e10
    minBerAllowed=1e-8

    # delay specified time in case of IO error, then retry
    delayOnErrorSec=5

    def __init__(self,portName):
        self.portName=portName
        if portName.lower()=='usb':
            self.port=usb.core.find(idVendor=self.usbVid, idProduct=self.usbPid)
        else:
            self.port = serial.Serial(
                port=portName,
                baudrate=19200,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                bytesize=serial.EIGHTBITS,
                timeout=10
            )
    
    @staticmethod
    def _getCrc(crcBase):
        crc = 0
        for x in crcBase:
            crc ^= x
        crc=crc.to_bytes(1,byteorder='little')
        return crc

    @staticmethod
    def _hex2float(data):
        m,deg=data
        deg-=127
        m='1'+'{0:08b}'.format(m)
        res=0
        for i in range(9):
            res+=(2**(deg-i))*int(m[i])
        return res

    def _payload2message(self,payload):
        syncByte=b'\x55'
        devId=b'\x01'
        cmdLen=(len(payload)+1).to_bytes(2,byteorder='little')
        # контрольная сумма для crcBase (XOR)
        crcBase=devId+cmdLen+payload
        crc=self._getCrc(crcBase)
        message=syncByte + devId + cmdLen + payload + crc
        return message


    def _message2payload(self,message):
        syncByte, devId, len1, len2, *payload, crc = message
        crc=crc.to_bytes(1,byteorder='little')
        crcBase=[devId,len1,len2]+payload
        realCrc=self._getCrc(crcBase)
        
        if crc!=realCrc:
            raise Exception('got wrong sync crc from device')
        return bytes(payload)

    def _askDeviceCom(self,message):
        # print('>>> head',message[:4].hex(),'cmd',message[4:-1].hex(),'crc',message[-1:].hex())
        self.port.write(message)
        head = self.port.read(4)
        if head[0]!=85:
            raise Exception('got wrong sync byte from device:'+str(head[0]))
        l=head[3]*256+head[2]
        # print('<<< head',head.hex(),'data',l,'bytes...', end='')    
        data = self.port.read(l)
        # print('OK')
        return head+data


    def _askDeviceUsb(self,message):
        bulkRead=0x82
        bulkWrite=0x02
        blockSize=64

        l=self.port.write(bulkWrite, message)
        if l!=len(message):
            raise Exception('error writing data to USB device')

        # reading 1st fixed-size block
        res=bytes(self.port.read(bulkRead,blockSize))

        head = res[:4]
        if head[0]!=85:
            raise Exception('got wrong sync byte from device:'+str(head[0]))
        # got data len (without header)
        l=head[3]*256+head[2]
        # print('<<< head',head.hex(),'data',l,'bytes...', end='')    

        # calc how many blocks are need for full message
        # 4 is the header length
        blocksN=(l+4)//blockSize + (1 if (l+4)%blockSize>0 else 0)

        # read rest blocks,first block was already read
        for i in range(blocksN-1):
            res+=bytes(self.port.read(bulkRead,blockSize))

        # trim data by header+specified data length
        res=res[:l+4]

        # print('OK')
        return res

    def close(self):
        if self.portName.lower()=='usb':
            usb.util.dispose_resources(self.port)
        else:
            self.port.close()

    def request(self,data):
        requestMsg=self._payload2message(data)
        if self.portName.lower()=='usb':
            replyMsg=self._askDeviceUsb(requestMsg)
        else:
            replyMsg=self._askDeviceCom(requestMsg)

        return self._message2payload(replyMsg)


    # ****** planar device command implementation *******
    def command1(self,startFreq=None,endFreq=None):
        # scan frequency range. Return list of level values
        req=struct.pack("<2B2H",1,0,startFreq,endFreq)    
        repl=self.request(req)

        if self.portName.lower()=='usb':
            levelCount=int((len(repl)-3)/2)
            command, status, reserve, *level = struct.unpack('<3B'+str(levelCount)+'H', repl)
            level=[i/10 for i in level]    
            res={'command':command, 'status':status,'level':level}
        else:
            levelCount=int((len(repl)-1)/2)
            command,*level = struct.unpack('<B'+str(levelCount)+'H', repl)
            level=[i/10 for i in level]    
            res={'command':command, 'level':level}
        
        if command!=1:
            raise Exception('got wrong command code from device:',command)
        return res


    def command28(self,freq=None):
        # set frequency to DVB-T2 tune
        command=b'\x1c'
        atten=b'\x04'
        freq=struct.pack("<H",freq)
        planData=b'\x00\x00\x00'
        mode=b'\x00'
        reserve=b'\x00\x00\x00'
        req=command+atten+freq+planData+mode+reserve
        repl=self.request(req)
        command,status = struct.unpack('<2B', repl)
        res={'command':command, 'status':status}
        return res


    def command29(self):
        # got measure result for frequency from command 28
        # got 0 or wrong result if device is not locked yet
        command=b'\x1d'
        repl=bytes(self.request(command))
        command=repl[0]
        status=repl[1]
        mer=(repl[2]+repl[3]*256.0)/10.0
        pre_ber=self._hex2float(repl[4:6])
        pre_ber=0 if pre_ber<self.minBerAllowed or pre_ber>self.maxBerAllowed else pre_ber        
        post_ber=self._hex2float(repl[8:10])
        post_ber=0 if post_ber<self.minBerAllowed or post_ber>self.maxBerAllowed else post_ber
        return {'command':command,'status':status,'mer':mer,'pre_ber':pre_ber,'post_ber':post_ber}      


    def command46(self, freq=None):
        # analog/digital level measurement

        command = b'\x2e'
        mode=b'\x00'
        # first bit =1 - digital channel
        # last 10 bits - frequency in mhz
        freq=struct.pack('<H',int('100000'+'{0:010b}'.format(freq),2))
        noise = b'\x00'
        channel_width = b'\x40'
        comment = b'\x00\x00\x00\x00\x00\x00\x00'
        req=command+mode+freq+noise+channel_width+comment
        repl=self.request(req)
        command,status,reserve,rssi,LevNoise,LevAudio = struct.unpack('<3B3H', repl)

        # 1) convert to 16 bit
        # 2) take last 15 bit (it is a level value)
        # 3) convert to int and divide by 10
        rssi=int('{0:016b}'.format(rssi)[-15:],2)/10
        return {'command':command, 'status':status, 'rssi':rssi}


    def command52(self):
        # start lnb
        command = b'\x34'
        action=b'\x01'
        lnb_voltage=b'\x00\x00\x00\x00'
        req=command+action+lnb_voltage
        self.request(req)


    def measureBer(self,freq):
        res={'deviceLock':False,'mer':0,'pre_ber':0,'post_ber':0}
        # start LNB
        self.command52()

        # set frequency to tune
        tune=self.command28(freq)
        if tune['status']!=0:
            print('can not tune to frequency')
            return res

        retryCount=int(self.berMeasureTimeoutSec//self.berMeasureIntervalSec)+1
        for i in range(retryCount):
            # trying to measure mer and ber
            s=self.command29()
            status, mer, pre_ber, post_ber = s['status'],s['mer'],s['pre_ber'],s['post_ber']

            # device is locked if 2 last bits of status are 1
            res['deviceLock']='{0:08b}'.format(status)[-2:]=='11'
            if res['deviceLock']:
                res['mer']=mer
                res['pre_ber']=pre_ber
                res['post_ber']=post_ber

                if 0 not in [mer,pre_ber]:
                    break
            time.sleep(self.berMeasureIntervalSec)

        return res

# **************************** begin device testing ************************************
if __name__=='__main__':

 
    #dev=itPlanar('COM5')
    dev=ItPlanar('USB')

    # print(dev.command1(startFreq=529,endFreq=531))
    
    
    print(dev.measureBer(freq=530))
    # print(dev.command46(freq=530))
    # print(dev.command46(freq=730))
    # print(dev.measureBer(freq=730))
    # print(dev.command46(freq=530))
    # print(dev.command46(freq=730))



    dev.close()


