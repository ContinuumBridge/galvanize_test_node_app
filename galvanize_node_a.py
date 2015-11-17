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
NODE_ID = 47
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
INTERVALS = {
    "ts1": 3,
    "ts2": 6,
    "ts3": 4,
    "ts4": 8,
    "ts5": 30,
    "tr1": 360,
    "tr2": 3600,
    "t_long_press": 3,
    "t_reset_press": 8,
    "t_start_press": 3,
    "t_search_max": 30,
    "t_keep_awake": 5
}

class Galvanize():
    def __init__(self):
        self.displayMessage = {
            "m1": ["Press to call for service", "", ""],
            "m2": ["Your request has been sent", "", ""],
            "m3": ["Cancelling request", "", ""],
            "m4": ["", "", ""],
            "initial": ["Press button for", "3 seconds to connect", "to network"],
            "search": ["Searching for network", "", ""],
            "search_failed": ["No network found", "Press to continue", ""],
            "connecting": ["Trying to connect to network", "Please wait", ""],
            "commsProblem": ["Communication problem", "Temporarily not in use", ""],
            "commsFailed": ["Communication problem", "Button not in use", ""]
        }
        self.displayFonts = {
            "m1": "medium",
            "m2": "medium",
            "m3": "large",
            "m4": "small",
            "initial": "medium",
            "search": "medium",
            "search_failed": "medium",
            "connecting": "medium",
            "commsProblem": "medium",
            "commsFailed": "medium"
        }
        self.numberLines = {
            "m1": 1,
            "m2": 1,
            "m3": 1,
            "m4": 0,
            "initial": 3,
            "search": 1,
            "search_failed": 2,
            "connecting": 2,
            "commsProblem": 2,
            "commsFailed": 2
        }
        self.buttonPressTime        = 0
        self.currentDisplay         = "m1"
        self.nodeState              = "initial"
        self.nodeAddress                 = 0xFFFF
        self.bridgeAddress          = None
        self.lprsID                 = None
        self.revertMessage          = True
        self.radioOn                = False
        self.sending                = False
        self.starting               = True

    def setDisplay(self, index):
        text = self.displayMessage[index][0]
        if self.numberLines[index] > 1:
            text += "\n" + self.displayMessage[index][1]
        if self.numberLines[index] > 2:
            text += "\n" + self.displayMessage[index][2]
        msg = {
            "id": self.id,
            "status": "user_message",
            "body": "Display: " + text
        }
        self.sendManagerMessage(msg)
        self.cbLog("info", "Display: " + text + ", font: " + self.displayFonts[index])

    def onButtonPress(self, buttonState, timeStamp):
        if buttonState == 1:
            self.buttonPressTime = timeStamp
        elif buttonState == 0:
            pressedTime = timeStamp - self.buttonPressTime 
            if pressedTime > INTERVALS["t_reset_press"]:
                self.nodeState = "initial"
                self.setDisplay("initial")
            elif self.nodeState == "initial":
                if pressedTime > INTERVALS["t_start_press"]:
                    self.nodeState = "search"
                    self.setDisplay("search")
                    self.radioOn = True
                    self.cbLog("debug", "radio on")
                    self.searchID = reactor.callLater(INTERVALS["t_search_max"], self.searchTimeout)
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
                self.nodeState = "normal"
                self.setDisplay("m1")
            elif self.nodeState == "search":
                pass  # Only get out of this state by finding network or long press or timeout
            elif self.nodeState == "search_failed":
                self.nodeState = "initial"
                self.setDisplay("initial")
            elif self.nodeState == "comms_failed":
                pass
            else:
                self.cbLog("warning", "State machine in unknown state: " + self.nodeState)
        self.cbLog("debug", "onButtonPress, end state: " + self.nodeState)

    def endRevert(self):
        if self.nodeState != "normal":
            self.nodeState = "normal"
            self.setDisplay("m1")

    def sendBattery(self):
        self.sendRadio("battery_status", struct.pack(">H", 100))

    def onIncludeGrant(self, data):
        addr, self.nodeAddress = struct.unpack(">IH", data)
        self.cbLog("debug", "onIncludeGrant, nodeID: " + str(self.nodeAddress) + ", addr: " + str(addr))

    def onConfig(self, data):
        configType = struct.unpack("B", data[0])[0]
        self.cbLog("debug", "configType: " + str(hex(configType)))
        if configType < 0x44:
            length = struct.unpack("B", data[1])[0]
            self.cbLog("debug", "config length: " + str(length))
            m = "m" + str((configType & 0xF0) >> 4)
            l = (configType & 0x0f) - 1
            self.cbLog("debug", "m: " + m + ", l: " + str(l))
            self.displayMessage[m][l] = str(data[2:length+2])
            self.cbLog("debug", "new m1: " + str(self.displayMessage["m1"]))
        elif configType & 0xF0 == 0xF0:
            m = "m" + str(configType & 0x0F)
            info = struct.unpack("B", data[1])
            font = FONT_INDEX[(info & 0xF0) >> 4]
            numLines = info & 0x0F
            self.cbLog("debug", "m: " + m + ", font: " + str(font) + ", numLines: " + str(numLines))
            self.displayFonts[m] = font
            self.displayLines[m] = numLines
        elif configType & 0xF0 == 0xB0:
            self.revertMessage = struct.unpack("B", data[1]) & 1
        elif configType & 0xF0 == 0xD0:
            display = DISPLAY_INDEX[struct.unpack("B", data[1])]
            self.setDisplay(display)
        else:
            self.cbLog ("info", "Unrecognised config type: " + str(hex(configType)))

    def wakeup(self, disconnected=False):
        try:
            self.wakeupID.cancel()
        except: 
            self.cbLog("debug", "wakeup called at end of normal time")
        self.sendRadio("woken_up")

    def goToSleep(self):
        self.radioOn = False
        self.cbLog("debug", "radio off")

    def setWakeup(self, wakeup):
        try:
            self.wakeupID.cancel()
        except:
            self.cbLog("debug", "setWakeup. Nothing to cancel")
        if wakeup == 0:
            self.wakeupID = reactor.callLater(INTERVALS["t_keep_awake"], self.goToSleep)
        else:
            self.wakeupID = reactor.callLater(wakeup*2, self.wakeup)

    def reconnect(self):
        self.radioOn = True
        self.cbLog("debug", "radio on")
        self.setDisplay("commsFailed")
        self.nodeState = "search"
        self.wakeupID = reactor.callLater(INTERVALS["tr2"], self.reconnect)

    def onRadioMessage(self, message):
        #if self.starting:
        #    self.setDisplay("initial")
        #    self.starting = False
        destination = struct.unpack(">H", message[0:2])[0]
        self.cbLog("debug", "Received. Rx: destination: " + str("{0:#0{1}X}".format(destination,6)) + ", radioOn: " + str(self.radioOn))
        if self.radioOn:
            destination = struct.unpack(">H", message[0:2])[0]
            if destination == self.nodeAddress or destination == BEACON_ADDRESS or destination == GRANT_ADDRESS:
                source, hexFunction, length = struct.unpack(">HBB", message[2:6])
                function = (key for key,value in FUNCTIONS.items() if value==hexFunction).next()
                #hexMessage = message.encode("hex")
                #self.cbLog("debug", "hex message after decode: " + str(hexMessage))
                self.cbLog("debug", "source: " + str("{0:#0{1}X}".format(source,6)))
                self.cbLog("debug", "Rx: function: " + function)
                self.cbLog("debug", "Rx: length: " + str(length))
                if length > 6:
                    wakeup = struct.unpack(">H", message[5:7])[0]
                    #reactor.callFromThread(self.cbLog, "debug", "wakeup: " + str(wakeup))
                else:
                    wakeup = 0
                if length > 8:
                    payload = message[8:]
                else:
                    payload = ""
                hexPayload = payload.encode("hex")
                self.cbLog("debug", "Rx: payload: " + str(hexPayload) + ", length: " + str(len(payload)))
    
                if function == "beacon":
                    if self.nodeState == "search":
                        self.bridgeAddress = source 
                        self.nodeState = "include_req"
                        self.sendRadio("include_req", struct.pack("I", NODE_ID))
                        self.setDisplay("connecting")
                elif function == "include_grant":
                    self.nodeState = "normal"
                    self.setDisplay("m1")
                    self.sendRadio("ack")
                    self.onIncludeGrant(payload)
                    self.acknowledged()
                elif function == "config":
                    self.onConfig(payload)
                    self.sendRadio("ack")
                    self.acknowledged()
                elif function == "send_battery":
                    self.sendBattery
                elif function == "ack":
                    self.acknowledged()
                else:
                    self.cbLog ("info", "Unrecognised radio function: " + str(function))
                if function != "beacon":
                    self.setWakeup(wakeup)
    
    def searchTimeout(self):
        if self.nodeState == "search":
            self.nodeState = "search_failed"
            self.setDisplay("search_failed")

    def sendRadio(self, function, data = None):
        if self.sending:
            self.cbLog("warning", "Could not send " + function + " message because another message is being sent")
            return
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
            self.sendMessage(msg, self.lprsID)
        #except Exception as ex:
        #    self.cbLog("warning", "Problem formatting message. Exception: " + str(type(ex)) + ", " + str(ex.args))
        self.manageSend(1, msg)

    def waitTime(self, a, b):
        r =  float(random.randint(a*10, b*10))/10
        self.cbLog("debug", "waitTime: " + str(r))
        return r

    def manageSend(self, attempt, msg=None):
        self.cbLog("info", "manageSend, attempt: " + str(attempt) + ", sending: " + str(self.sending))
        if attempt ==1:
            self.sending = True
            self.beingSent = msg
            self.radioOn = True
            self.cbLog("debug", "radio on")
            self.sendMessage(self.beingSent, self.lprsID)
            self.cbLog ("debug", "Sending: " + str(self.beingSent))
            waitTime = self.waitTime(INTERVALS["ts1"], INTERVALS["ts2"])
            self.waitingID = reactor.callLater(waitTime, self.manageSend, 2)
        elif attempt == 2 and self.sending:
            self.sendMessage(self.beingSent, self.lprsID)
            waitTime = self.waitTime(INTERVALS["ts3"], INTERVALS["ts4"])
            self.waitingID = reactor.callLater(waitTime, self.manageSend, 3)
        elif attempt == 3 and self.sending:
            self.nodeState = "commsProblem"
            self.waitingID = reactor.callLater(INTERVALS["ts5"], self.manageSend, 4)
        elif attempt ==4 and self.sending:
            self.sendMessage(self.beingSent, self.lprsID)
            waitTime = self.waitTime(INTERVALS["ts1"], INTERVALS["ts2"])
            self.waitingID = reactor.callLater(waitTime, self.manageSend, 5)
        elif attempt == 5 and self.sending:
            self.sendMessage(self.beingSent, self.lprsID)
            waitTime = self.waitTime(INTERVALS["ts3"], INTERVALS["ts4"])
            self.waitingID = reactor.callLater(waitTime, self.manageSend, 6)
        elif attempt == 6 and self.sending:
            self.setDisplay("commsProblem")
            self.radioOn = False
            self.cbLog("debug", "radio off")
            self.wakeupID = reactor.callLater(INTERVALS["tr1"], self.reconnect)

    def acknowledged(self):
        try:
            self.waitingID.cancel()
        except:
            self.cbLog("debug", "acknowledged, nothing to cancel")
        self.sending = False

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
        if message["characteristic"] == "buttons":
            self.galvanize.onButtonPress(message["data"]["leftButton"], message["timeStamp"])

    def onConfigureMessage(self, managerConfig):
        self.galvanize = Galvanize()
        self.galvanize.cbLog = self.cbLog
        self.galvanize.id = self.id
        self.galvanize.sendMessage = self.sendMessage
        self.galvanize.sendManagerMessage = self.sendManagerMessage
        self.setState("starting")

if __name__ == '__main__':
    App(sys.argv)
