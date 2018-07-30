from libItPlanar import ItPlanar
import pika
import time
import json
from datetime import datetime

config=[
    {
        'agentName':'test1',
        'taskName':'ЦТВ',
        'taskId':'22901',
        'freqMhz':530,
        'mqIp':'127.0.0.1',
        'mqPort':5672,
        'mqUser':'rabbitmq',
        'mqPwd':'zoh5xahS',
        'mqVhost':'/',
        'mqExchange':'qos.result',
    },
    {
        'agentName':'test2',
        'taskName':'ЦТВ',
        'taskId':'22902',
        'freqMhz':730,        
        'mqIp':'127.0.0.1',
        'mqPort':5672,
        'mqUser':'rabbitmq',
        'mqPwd':'zoh5xahS',
        'mqVhost':'/',
        'mqExchange':'qos.result',
    }
]

# common settings
pollPeriod=10
sendPeriod=60

# internal. Not to edit.
berToPoll=0
lastAggPollN=0
lastAggSendN=0
timeStampFormat = "%Y%m%d%H%M%S"


def sendData(data,conf):
    print('sending',conf['agentName'],'data to rabbitMQ (',len(data),'results)...',end='')

    msgRoutingKey="agent-"+conf['agentName']

    msgHeaders = {
        '__TypeId__': "com.tecomgroup.qos.communication.message.ResultMessage",
        'version': "1.0"
    }

    msgBody={
        "originName" : conf['agentName'],
        "taskKey" : conf['agentName']+".RfMeasurement."+conf['taskId'],
        "taskDisplayName" : conf['taskName'],
        "resultType" : "SINGLE_VALUE_RESULT",
        "results" : data
    }

    amqpLink = pika.BlockingConnection(
        pika.ConnectionParameters(
            conf["mqIp"],
            conf['mqPort'],
            conf["mqVhost"],
            pika.PlainCredentials(conf["mqUser"], conf["mqPwd"])))
    channel = amqpLink.channel()

    channel.basic_publish(
        exchange=conf["mqExchange"],
        routing_key=msgRoutingKey,
        properties=pika.BasicProperties(
            delivery_mode=2,  # make message persistent
            content_type='application/json',
            content_encoding='UTF-8',
            priority=0,
            expiration="86400000",
            headers=msgHeaders),
        body=json.dumps(msgBody).encode('UTF-8')
    )

    amqpLink.close()
    print('OK')  

def prepareData(data,timeStr):
    # convert data to vision format
    # data IT15+ber:
    # {'command': 46, 'status': 0, 'RSSI': 53.8, 'deviceLock': True, 'mer': 27.6, 'pre_ber': 0.000698089599609375, 'post_ber': 0}
    # data IT15 without ber:
    # {'command': 46, 'status': 0, 'RSSI': 60.6}
    p={}
    if 'rssi' in data:
        # rssi was measured
        p['rssi']="{:.16f}".format(data['rssi'])
    if 'deviceLock' in data:
        # ber was measured
        p['mer']="{:.16f}".format(data['mer'])
        p['pre_ber']="{:.16f}".format(data['pre_ber'])
        p['post_ber']="{:.16f}".format(data['post_ber'])
        p['signal_present']=str(int(data['deviceLock']))
    res={
        "resultDateTime":timeStr,
        "group" : "default",
        "parameters":p
    }
    return res


#dev=itPlanar('COM5')
dev=ItPlanar('USB')
dataToSend=[[] for i in range(len(config))]

while True:
    timeStamp=int(time.time())

    # sending data to rabbitmq
    aggSendN=int(timeStamp//sendPeriod)
    if aggSendN>lastAggSendN:
        # it is time to send a data
        lastAggSendN=aggSendN

        if [] not in dataToSend:
            for i in range(len(dataToSend)):
                sendData(dataToSend[i],config[i])
                dataToSend[i]=[]
    # endif new aggSendN

    # polling device for data
    aggPollN=int(timeStamp//pollPeriod)
    if (aggPollN>lastAggPollN):
        # it is time to make a poll
        lastAggPollN=aggPollN

        # result of current poll for all tasks
        pollResult=[None]*len(config)

        # timestamp to utc time string
        timeStr=datetime.strftime(datetime.utcfromtimestamp(timeStamp),timeStampFormat)
        print('agg period ',timeStr)
        
        # poll rssi for all tsks
        for i,task in enumerate(config):
            curRes=dev.command46(freq=config[i]['freqMhz'])
            pollResult[i]=curRes

        # poll ber for one task
        freq=config[berToPoll]['freqMhz']
        curRes=dev.measureBer(freq=freq)
        pollResult[berToPoll].update(curRes)

        # swich berToPoll to next item
        berToPoll+=1
        if berToPoll>=len(config):
            berToPoll=0

        # print poll results and store into dataToSend buffer
        for i,task in enumerate(config):
            print('task',config[i]['agentName'],pollResult[i])
            dataToSend[i]+=[prepareData(pollResult[i],timeStr)]
        # skip sleeping and check for new aggPollN
        continue
    # endif new aggPollN

    time.sleep(1)

dev.close()
