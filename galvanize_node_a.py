#!/usr/bin/env python
# galvanize_node_a.py
"""
Copyright (c) 2015 ContinuumBridge Limited
"""

import sys
import time
import json
import struct
from cbcommslib import CbApp
from cbconfig import *
from twisted.internet import reactor

ALERTS = {
    "pressed": struct.pack(">H" 0x0000),
    "user_cleared": struct.pack(">H", 0x0100),
    "service_cleared": struct.pack(">H", 0x0200)
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
MAX_SEARCH_TIME = 30

class Galvanize():
    def __init__(self):
        self.buttonPressTime = 0
        self.displayMessage = {
            "m1": ["", "", ""],
            "m2": ["", "", ""],
            "m3": ["", "", ""],
            "m4": ["", "", ""],
            "initial": ["Press button to connect", "to a network", ""],
            "search": ["Searching for network", "", ""],
            "search_failed": ["No network found", "Press to continue", ""],
            "connecting": ["Trying to connect to network", "Please wait", ""],
            "successfulConntect": ["Network connection successful", "", ""],
            "failedConnect": ["Network connection failed", "", ""],
            "commsProblem": ["Communication problem", "Temporarily not in use", ""],
            "commsFailed": ["Communication problem", "Button not in use", ""]
        }
        self.displayFonts = {
            "m1": "small",
            "m2": "small",
            "m3": "small",
            "m4": "small",
            "initial": "medium",
            "search": "medium",
            "search_failed": "medium",
            "connecting": "medium",
            "successfulConntect": "medium",
            "failedConnect": "medium",
            "commsProblem": "medium",
            "commsFailed": "medium"
        }
        self.numberLines = {
            "m1": 0,
            "m2": 0,
            "m3": 0,
            "m4": 0,
            "initial": 2,
            "search": 1,
            "search_failed": 2,
            "connecting": 2,
            "successfulConntect": 1,
            "failedConnect": 1,
            "commsProblem": 2,
            "commsFailed": 2
        }
        self.currentDisplay = "m1"
        self.nodeState = "initial"
        self.lprsID = None
        self.userClearable = True

    def setDisplay(self, index):
        msg = {
            "id": self.id,
            "status": "user_message",
            "body": self.displayMessage[index]
        }
        self.sendManagerMessage(msg)
        self.cbLog("info", "Display: " + self.displayMessage[index] + ", font: " + self.displayFonts[index])

    def onButtonPress(self, buttonState, timeStamp):
        if buttonState == 1:
            self.buttonPressTime = timeStamp
        elif buttonState == 0:
            pressedTime = timeStamp - self.buttonPressTime 
            if pressedTime > 20:
                self.nodeState = "initial"
                self.setDisplay("initial")
            elif self.nodeState == "normal":
                if pressedTime < 3:
                    self.nodeState = "pressed"
                    self.setDisplay("m2")
                    self.sendRadio("alert", "pressed")
            elif self.nodeState == "pressed":
                if pressedTime < 3:
                    self.nodeState = "reverting"
                    self.setDisplay("m3")
                    self.sendRadio("alert", "user_cleared")
                    reactor.callLater(5, self.endRevert)
                else:
                    self.nodeState = "normal"
                    self.setDisplay("m1")
                    self.sendRadio("alert", "service_cleared")
            elif self.nodeState == "reverting":
                self.nodeState = "normal"
                self.setDisplay("m1")
            elif self.nodeState == "initial":
                self.nodeState = "search"
                self.setDisplay("search")
                reactor.callLater(MAX_SEARCH_TIME, self.searchTimeout)
            elif self.nodeState == "search":
                pass  # Only get out of this state by finding network or long press
            elif self.nodeState == "search_failed":
                self.nodeState = "initial"
                self.setDisplay("initial")
            else:
                self.cbLog("warning", "State machine in unknown state: " + self.nodeState)

    def endRevert(self):
        if self.nodeState != "normal":
            self.nodeState = "normal"
            self.setDisplay("m1")

    def sendBattery(self):
        self.sendRadio("battery_status", struct.pack(">H" 100))

    def onConfig(self, data):
        configiType = struct.unpack("B", data[0])
        if configType < 0x44:
            length = struct.unpack("B", data[1])
            if configType == 0x11:
                self.displayMessage[m1[0]] = data[2:]
            elif configType == 0x12:
                self.displayMessage[m1[1]] = data[2:]
            elif configType == 0x12:
                self.displayMessage[m1[2]] = data[2:]
            elif configType == 0x21:
                self.displayMessage[m2[0]] = data[2:]
            elif configType == 0x22:
                self.displayMessage[m2[1]] = data[2:]
            elif configType == 0x22:
                self.displayMessage[m2[2]] = data[2:]
            elif configType == 0x31:
                self.displayMessage[m3[0]] = data[2:]
            elif configType == 0x32:
                self.displayMessage[m3[1]] = data[2:]
            elif configType == 0x32:
                self.displayMessage[m3[2]] = data[2:]
            elif configType == 0x41:
                self.displayMessage[m4[0]] = data[2:]
            elif configType == 0x42:
                self.displayMessage[m4[1]] = data[2:]
            elif configType == 0x42:
                self.displayMessage[m4[2]] = data[2:]
        elif configType & 0xF0 == 0xF0:
            info = struct.unpack("B", data[1])
            font = FONT_INDEX[(info & 0xF0) >> 4]
            numLines = info & 0x0F
            if configType == 0xF1:
                self.displayFonts[m1] = font
                self.numberLines[m1] = numLines
            elif configType == 0xF2:
                self.displayFonts[m2] = font
                self.numberLines[m2] = numLines
            elif configType == 0xF3:
                self.displayFonts[m3] = font
                self.numberLines[m3] = numLines
            elif configType == 0xF4:
                self.displayFonts[m4] = font
                self.numberLines[m4] = numLines
        elif configType & 0xF0 == 0xB0:
            self.userClearable = struct.unpack("B", data[1]) & 1
        elif configType & 0xF0 == 0xD0:
            display = DISPLAY_INDEX[struct.unpack("B", data[1])]
            self.setDisplay(display)
        else:
            self.cbLog ("info", "Unrecognised config type: " + str(configType))

    def onRadioMessage(function, data):
        if function == "beacon":
            if self.nodeState == "search":
                self.nodeState = "include_req"
                self.setDisplay("connecting")
        elif function == "include_grant":
            self.nodeState = "normal"
            self.sendRadio("ack")
        elif function == "config":
            self.onConfig(data)
        elif function == "send_battery":
            self.sendBattery
        elif function == "reinclude":
            self.sendRadio("include_req")
            self.nodeState = "including"
        else:
            self.cbLog ("info", "Unrecognised radio function: " + function)

    def searchTimeout(self):
        if self.nodeState == "search":
            self.nodeState = "search_failed"
            self.setDisplay("search_failed")

    def sendRadio(self, function, data = None):
        msg = {
            "id": self.id,
            "request": "command",
            "data": {
                "function": function,
                "data": data
            }
        }
        self.sendMessage(msg, self.lprsID)

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
            self.galvanize.onRadioMessage(message["data"]["function"], message["data"]["data"])
        if message["characteristic"] == "buttons":
            self.galvanize.onButtonPress(message["data"]["leftButton"], message["timeStamp"])

    def onConfigureMessage(self, managerConfig):
        self.galvanize = Galvanize()
        self.galvanize.cbLog = self.cbLog
        self.galvanize.sendManagerMessage = self.sendManagerMessage
        self.setState("starting")

if __name__ == '__main__':
    App(sys.argv)
