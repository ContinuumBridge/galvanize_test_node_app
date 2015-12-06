#!/usr/bin/env python
# galvanize_node_a.py
"""
Copyright (c) 2015 ContinuumBridge Limited
"""

import sys
import time
import json
import base64
import struct
import random
from cbcommslib import CbApp
from cbconfig import *
from twisted.internet import reactor

BEACON_ADDRESS      = 0xBBBB
GRANT_ADDRESS       = 0xBB00
NODE_ID             = 47
SLOT_TIME           = 80        # The length of a data sending slot
MAX_SLOTS           = 36        # The number of slots in a frame
FUNCTIONS = {
    "include_req": 0x00,
    "s_include_req": 0x01,
    "include_grant": 0x02,
    "reinclude": 0x04,
    "config": 0x05,
    "send_battery": 0x06,
    "alert": 0x09,
    "woken_up": 0x07,
    "ack": 0x08,
    "beacon": 0x0A
}
ALERTS = {
    "pressed": struct.pack(">H", 0x0000),
    "cleared": struct.pack(">H", 0x0100),
    "battery": struct.pack(">H", 0x0200)
}
FONT_INDEX = {
    1: "small",
    2: "medium",
    3: "large"
}
DISPLAY_INDEX = {
    1: "m1",
    2: "m2",
    3: "m3",
    4: "m4"
}

class Galvanize():
    def __init__(self):
        self.intervals = {
            "ts5": 30,
            "tr1": 360,
            "tr2": 3600,
            "t_long_press": 3,
            "t_reset_press": 8,
            "t_start_press": 3,
            "t_search_max": 30,
            "t_short_search_wait": 600,
            "t_long_search_wait": 3600,
            "t_keep_awake": 20,
            "t_sleep": 60
        }
        self.displayMessage = {
            "m1": ["Push here", "to call for service", ""],
            "m2": ["Your request has been sent", "", ""],
            "m3": ["Cancelling request", "", ""],
            "m4": ["", "", ""],
            "initial": ["Push here for", "3 seconds to connect", "to network"],
            "search": ["Searching for network", "", ""],
            "connecting": ["Trying to connect to network", "Please wait", ""],
            "commsProblem": ["Communication problem", "Button not in use", ""]
        }
        self.displayFonts = {
            "m1": "medium",
            "m2": "medium",
            "m3": "large",
            "m4": "small",
            "initial": "medium",
            "search": "medium",
            "connecting": "medium",
            "commsProblem": "medium"
        }
        self.numberLines = {
            "m1": 2,
            "m2": 1,
            "m3": 1,
            "m4": 0,
            "initial": 3,
            "search": 1,
            "connecting": 2,
            "commsProblem": 2
        }
        self.radioQueue             = []
        self.beaconDelay            = 32*0.08
        self.buttonPressTime        = 0
        self.currentDisplay         = "m1"
        self.nodeState              = "initial"
        self.nodeAddress            = 0xFFFF
        self.bridgeAddress          = None
        self.lprsID                 = None
        self.revertMessage          = True
        self.radioOn                = False

    def setDisplay(self, index):
        self.cbLog("info", "Display: -----------------------------------")
        self.cbLog("info", "Display: " + self.displayMessage[index][0])
        if self.numberLines[index] > 1:
            self.cbLog("info", "Display: " + self.displayMessage[index][1])
        if self.numberLines[index] > 2:
            self.cbLog("info", "Display: " + self.displayMessage[index][2])
        self.cbLog("info", "Display: -----------------------------------")
        self.cbLog("info", "Display font: " + self.displayFonts[index])
        self.cbLog("info", "Display: -----------------------------------")

    def onButtonPress(self, buttonState, timeStamp):
        if buttonState == 1:
            self.buttonPressTime = timeStamp
        elif buttonState == 0:
            pressedTime = timeStamp - self.buttonPressTime 
            if pressedTime > self.intervals["t_reset_press"]:
                self.nodeState = "initial"
                self.setDisplay("initial")
            elif self.nodeState == "initial":
                if pressedTime > self.intervals["t_start_press"]:
                    self.nodeState = "search"
                    self.setDisplay("search")
                    self.switchRadio(True)
            elif self.nodeState == "normal":
                self.nodeState = "clearable"
                self.nodeState = "pressed"
                self.setDisplay("m2")
                self.sendRadio("alert", ALERTS["pressed"])
            elif self.nodeState == "pressed":
                if pressedTime > 3:
                    self.sendRadio("alert", ALERTS["cleared"])
                    if self.revertMessage:
                        self.nodeState = "reverting"
                        self.setDisplay("m3")
                        reactor.callLater(5, self.endRevert)
                    else:
                        self.nodeState = "normal"
                        self.setDisplay("m1")
            elif self.nodeState == "reverting":
                pass  # This state exited by delayed endRevert function
            elif self.nodeState == "search":
                pass  # Only get out of this state by finding network or long press or timeout
            else:
                self.cbLog("warning", "State machine in unknown state: " + self.nodeState)
            self.cbLog("debug", "onButtonPress, end state: " + self.nodeState)

    def endRevert(self):
        if self.nodeState != "normal":
            self.nodeState = "normal"
            self.setDisplay("m1")

    def searchTimeout(self, attempt):
        """
        Implements most of the beacon search process state machine
        This function is called with attempt=0 if a beacon message has not been found after 30s of searching.
        It then goes through a process of searching again after 10 mins and then after every hour. 
        This goes on forever until a beacon is found or the node is reset.
        Note that self.searchID is cancelled if a message is received & hence this function is not called.
        """
        if attempt == 0:
            self.radioOn = False
            self.setDisplay("commsProblem")
            self.nodeState = "search":
            self.searchID = reactor.callLater(self.intervals["t_short_search_wait"], self.searchTimeout, 1)
        elif attempt == 1:
            self.radioOn = True
            self.searchID = reactor.callLater(self.intervals["t_search_max"], self.searchTimeout, 2)
        elif attempt == 2:
            self.radioOn = False
            self.searchID = reactor.callLater(self.intervals["t_long_search_wait"], self.searchTimeout, 3)
        elif attempt == 3
            self.radioOn = True
            self.searchID = reactor.callLater(self.intervals["t_search_max"], self.searchTimeout, 2)

    def switchRadio(self, state):
        try:
            self.searchID.cancel()  # Stops search timeout when we switch radion on or off
        except Exception as ex:
            self.cbLog("debug", "No searchID to cancel. Exception: " + str(type(ex)) + ", " + str(ex.args))
        if state == False:
            if not self.radioQueue:
                self.radioOn = False
        else:
            self.radioOn = True
            # As soon as radio is switched on searchTimeout is called for t_search_max later.
            # self.searchID is cancelled when a message is received. Hence searchTimeout will not be called.
            self.searchID = reactor.callLater(self.intervals["t_search_max"], self.searchTimeout, 0)
        self.cbLog("debug", "radioOn: " + str(self.radioOn))

    def wakeup(self, disconnected=False):
        try:
            self.wakeupID.cancel()
        except: 
            self.cbLog("debug", "wakeup called at end of normal time")
        self.sendRadio("woken_up")

    def goToSleep(self):
        self.switchRadio(False)
        self.wakeupID = reactor.callLater(self.intervals["t_sleep"], self.wakeup)
        self.cbLog("debug", "setWakeup, sleeping for " + str(self.intervals["t_sleep"]) + " seconds")

    def setWakeup(self, wakeup):
        try:
            self.wakeupID.cancel()
        except:
            self.cbLog("debug", "setWakeup. Nothing to cancel")
        if wakeup == 0:
            self.wakeupID = reactor.callLater(self.intervals["t_keep_awake"], self.goToSleep)
            self.cbLog("debug", "setWakeup, staying awake for " + str(self.intervals["t_keep_awake"]) + " seconds")
        else:
            self.intervals["t_sleep"] = wakeup*2
            self.goToSleep()

    def sendBattery(self):
        self.sendRadio("battery_status", struct.pack(">H", 100))

    def onIncludeGrant(self, data):
        addr, self.nodeAddress = struct.unpack(">IH", data)
        self.intervals["tWait"] = (self.nodeAddress & 0x1F) * 0.08
        self.cbLog("debug", "onIncludeGrant, nodeID: " + str(self.nodeAddress) + ", addr: " + str(addr) + ", tWait: " + str(self.intervals["tWait"]))

    def onConfig(self, data):
        configType = struct.unpack("B", data[0])[0]
        self.cbLog("debug", "configType: " + str(hex(configType)))
        if configType < 0x44:
            length = struct.unpack("B", data[1])[0]
            self.cbLog("debug", "config length: " + str(length))
            m = "m" + str((configType & 0xF0) >> 4)
            l = (configType & 0x0f) - 1
            self.displayMessage[m][l] = str(data[2:length+2])
            self.cbLog("debug", "new message, m: " + str(m) + ", l: " + str(l) + ", line: " + str(self.displayMessage[m][l]))
        elif configType & 0xF0 == 0xF0:
            m = "m" + str(configType & 0x0F)
            info = struct.unpack("B", data[1])[0]
            font = FONT_INDEX[(info & 0xF0) >> 4]
            numLines = info & 0x0F
            self.cbLog("debug", "m: " + m + ", font: " + str(font) + ", numLines: " + str(numLines))
            self.displayFonts[m] = font
            self.numberLines[m] = numLines
        elif configType & 0xF0 == 0xB0:
            self.revertMessage = struct.unpack("B", data[1]) & 1
        elif configType & 0xF0 == 0xD0:
            display = DISPLAY_INDEX[struct.unpack("B", data[1])]
            self.setDisplay(display)
        else:
            self.cbLog ("info", "Unrecognised config type: " + str(hex(configType)))

    def onRadioMessage(self, message):
        if self.radioOn:
            destination = struct.unpack(">H", message[0:2])[0]
            if destination == self.nodeAddress or destination == BEACON_ADDRESS or destination == GRANT_ADDRESS:
                try:
                    self.searchID.cancel()  # Stops 30 second search timeout when we receive a message
                except Exception as ex:
                    self.cbLog("debug", "No searchID to cancel. Exception: " + str(type(ex)) + ", " + str(ex.args))
                source, hexFunction, length = struct.unpack(">HBB", message[2:6])
                function = (key for key,value in FUNCTIONS.items() if value==hexFunction).next()
                self.cbLog("debug", "onRadioMessage, source: " + str("{0:#0{1}x}".format(source,6)) + ", function: " + function)
                if length > 6:
                    wakeup = struct.unpack(">H", message[6:8])[0]
                    reactor.callFromThread(self.cbLog, "debug", "wakeup: " + str(wakeup))
                else:
                    wakeup = 0
                if length > 8:
                    payload = message[8:length+1]
                    self.cbLog("debug", "Rx: payload: " + str(payload.encode("hex")) + ", length: " + str(len(payload)))
                else:
                    payload = ""
                if function == "beacon":
                    self.manageSend()
                    if self.nodeState == "search":
                        self.bridgeAddress = source 
                        self.nodeState = "include_req"
                        self.sendRadio("include_req", struct.pack("I", NODE_ID))
                        self.setDisplay("connecting")
                elif function == "include_grant":
                    self.nodeState = "normal"
                    self.setDisplay("m1")
                    self.onIncludeGrant(payload)
                    self.sendRadio("ack")
                elif function == "config":
                    self.onConfig(payload)
                    self.sendRadio("ack")
                elif function == "send_battery":
                    self.sendBattery
                elif function == "ack":
                    self.acknowledged()
                else:
                    self.cbLog ("info", "Unrecognised radio function: " + str(function))
                if function != "beacon":
                    self.setWakeup(wakeup)
    
    def sendRadio(self, function, data = None):
        if True:
        #try:
            length = 6
            if data:
                length += len(data)
                self.cbLog("debug", "data length: " + str(length))
            m = ""
            m += struct.pack(">H", self.bridgeAddress)
            m += struct.pack(">H", self.nodeAddress)
            m+= struct.pack("B", FUNCTIONS[function])
            m+= struct.pack("B", length)
            self.cbLog("debug", "length: " +  str(length))
            if data:
                m += data
            hexPayload = m.encode("hex")
            self.cbLog("debug", "Tx: sending: " + str(hexPayload))
            msg= {
                "id": self.id,
                "request": "command",
                "data": base64.b64encode(m)
            }
            self.queueRadio(msg, function)
        #except Exception as ex:
        #    self.cbLog("warning", "Problem formatting message. Exception: " + str(type(ex)) + ", " + str(ex.args))

    def randomWait(self):
        r =  float(random.randint(0, MAX_SLOTS*SLOT_TIME))/1000
        self.cbLog("debug", "waitTime: " + str(r))
        return r

    def queueRadio(self, msg, function):
        toQueue = {
            "message": msg,
            "function": function,
            "attempt": 0
        }
        if function == "ack":
            self.radioQueue.insert(0, toQueue)
        else:
            self.radioQueue.append(toQueue)
        self.switchRadio(True)
        self.cbLog("debug", "queueRadio, toQueue: " + str(toQueue["function"]))

    def manageSend(self):
        if self.radioQueue:
            self.cbLog("debug", "manageSend, radioQueue: " + str(json.dumps(self.radioQueue, indent=4)))
            if self.radioQueue[0]["attempt"] == 0:
                reactor.callLater(self.beaconDelay, self.delayedSend)
                self.radioQueue[0]["attempt"] += 1
            elif self.radioQueue[0]["attempt"] == 1:
                reactor.callLater(self.randomWait(), self.delayedSend)
                self.radioQueue[0]["attempt"] += 1
            elif self.radioQueue[0]["attempt"] == 2:
                reactor.callLater(self.randomWait(), self.delayedSend)
                self.radioQueue[0]["attempt"] += 1
            elif self.radioQueue[0]["attempt"] > 2 and self.radioQueue[0]["attempt"] < 9:
                self.radioQueue[0]["attempt"] += 1 
            elif self.radioQueue[0]["attempt"] == 9:
                reactor.callLater(self.beaconDelay, self.delayedSend)
                self.radioQueue[0]["attempt"] += 1
            elif self.radioQueue[0]["attempt"] == 10:
                reactor.callLater(self.randomWait(), self.delayedSend)
                self.radioQueue[0]["attempt"] += 1
            elif self.radioQueue[0]["attempt"] == 11:
                reactor.callLater(self.randomWait(), self.delayedSend)
                self.radioQueue[0]["attempt"] += 1
            elif self.radioQueue[0]["attempt"] == 12:
                reactor.callLater(self.randomWait(), self.delayedSend)
                self.radioQueue = []
                reactor.callLater(self.goToSleep, self.delayedSend)
                self.setDisplay("commsProblem")

    def delayedSend(self):
        self.sendMessage(self.radioQueue[0]["message"], self.lprsID)
        # include_req & ack are only sent once, so delete them from the queue as soon as they are sent
        if self.radioQueue[0]["function"] == "include_req" or self.radioQueue[0]["function"] == "ack":
            del(self.radioQueue[0])

    def acknowledged(self):
        try:
            del(self.radioQueue[0])  # Delete the message at the front of the queue
        except:
            self.cbLog("debug", "acknowledged, nothing to delete from radioQueue")

class App(CbApp):
    def __init__(self, argv):
        self.appClass = "control"
        self.state = "stopped"
        self.devices = []
        self.idToName = {} 
        self.buttonsID = None
        # Super-class init must be called
        CbApp.__init__(self, argv)

    def setState(self, action):
        self.state = action
        msg = {"id": self.id,
               "status": "state",
               "state": self.state}
        self.sendManagerMessage(msg)

    def onAdaptorService(self, message):
        #self.cbLog("debug", "onAdaptorService, message: " + str(message))
        for p in message["service"]:
            if p["characteristic"] == "galvanize_button":
                req = {"id": self.id,
                       "request": "service",
                       "service": [
                                   {"characteristic": "galvanize_button",
                                    "interval": 0
                                   }
                                  ]
                      }
                self.sendMessage(req, message["id"])
                self.galvanize.lprsID = message["id"]
            elif p["characteristic"] == "buttons":
                req = {"id": self.id,
                       "request": "service",
                       "service": [
                                     {"characteristic": "buttons",
                                      "interval": 0
                                     }
                                  ]
                      }
                self.sendMessage(req, message["id"])
                self.buttonsID = message["id"]
        self.setState("running")

    def onAdaptorData(self, message):
        #self.cbLog("debug", "onAdaptorData, message: " + str(message))
        if message["characteristic"] == "galvanize_button":
            self.galvanize.onRadioMessage(base64.b64decode(message["data"]))
        elif message["characteristic"] == "buttons":
            self.galvanize.onButtonPress(message["data"]["leftButton"], message["timeStamp"])

    def onConfigureMessage(self, managerConfig):
        self.galvanize = Galvanize()
        self.galvanize.cbLog = self.cbLog
        self.galvanize.id = self.id
        self.galvanize.sendMessage = self.sendMessage
        self.galvanize.sendManagerMessage = self.sendManagerMessage
        self.galvanize.setDisplay("initial")
        self.setState("starting")

if __name__ == '__main__':
    App(sys.argv)
