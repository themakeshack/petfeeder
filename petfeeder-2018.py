#!/usr/bin/python3


# This is the main program that does the feeding, checking for email and buttons
# This gets invoked from a shell script called petfeeder.sh which itself gets invoked from cron on reboot
# The petfeeder.sh takes care of restarting this program if it were to crash for some reason
# This program maintains an error log at /home/petfeeder/petfeeder.err
# Its STDOUT is available at /home/petfeeder/petfeeder.log
#
# Changelog
# petfeeder4.py - Added Chuck Norris jokes API call
# petfeeder5.py - Added file based saving of lastFeed to preserve across reboots
# petfeeder6.py - Added Numbers Trivia API call with a switch for Chuck Norris and/or Numbers Trivia
# petfeeder7.py - Added have_internet() to check for internet presence. There were too many crashes in checkmail() or the api callers due to internet unavailability
# petfeeder8.py - Added camera and picture emailing
# petfeeder9.py - Added google spreadsheet update
# petfeeder-new.py - Major rewrite to include GMail APIs. Upgrade to Jessie and the new python libraries (urllib3). New checks for camera presence
# petfeeder-new1.py - Added LED lighting support
# WIP petfeeder-2018.py - change to a multithreaded program to make button pushes realtime

import os
import sys
import time
import threading

import RPi.GPIO as GPIO
from Adafruit_CharLCD import Adafruit_CharLCD
import httplib2
import urllib3
import json
import html2text
import picamera
import gspread
import mailer
import subprocess
# from oauth2client.client import SignedJwtAssertionCredentials
from oauth2client.service_account import ServiceAccountCredentials

# Some switches to turn on or off to change program behavior
DEBUG = True  # Turns debugging on/off
MOTORON = False  # Enables or disables the motor - useful while debugging
CHUCKNORRIS = False  # Turns on/off Chuck Norris jokes in email replies
NUMBERTRIVIA = False  # Turns on/off Numers Trivia in email replies

# Files that we care about
LOGFILE = "/tmp/petfeeder.log"  # General purpoise log file
PICFILE = "/tmp/picfile.jpg"  # This is where the camera saves the picture
OAUTHFILE = "/home/pi/projects/petfeeder/petfeeder-gspread.json"  # File with OAUTH2 info
SPSHEET = "Pet Feeder"  # Google spreadsheet name

MAILSUBJECTS = ['Feed', 'When', 'Pic', "LightON", "LightOFF"]
emailid = "feedlucky@gmail.com"

# GPIO pins for LCD
lcd_rs = 25
lcd_en = 24
lcd_d4 = 23
lcd_d5 = 17
lcd_d6 = 21
lcd_d7 = 22
lcd_backlight = 4  # This is not used since the backlight control is through a manual potentiometer
# Define LCD column and row size for 16x2 LCD.
lcd_columns = 16
lcd_rows = 2

# GPIO pins for feeder control
MOTORCONTROLPIN = 19
FEEDBUTTONPIN = 6
RESETBUTTONPIN = 13

# GPIO pin for LED light
LEDLIGHT = 4

# Variables for feeding information
readyToFeed = False
feedInterval = 28800  # 28800  # This translates to 8 hours in seconds
FEEDFILE = "/home/pi/projects/petfeeder/lastfeed"
cupsToFeed = 1
motorTime = cupsToFeed * 23  # It takes 23 seconds of motor turning (~1.75 rotations) to get 1 cup of feed


# Tiny function to print DEBUG messages, can be set to null to turn off DEBUG info
def printdebug(mesg):
    global logFile
    logFile.write(mesg + '\n')
    if DEBUG:
        print(mesg)


def ledlight(command):
    global GPIO
    if command == "on":
        GPIO.output(LEDLIGHT, True)
    elif command == "off":
        GPIO.output(LEDLIGHT, False)


# Function that checks internet availability
def have_internet():
    printdebug("Entering have_internet")
    try:
        printdebug("Making http request ...")
        http = urllib3.PoolManager(timeout=3.0)
        http.request('GET', "http://www.google.com")
        printdebug("Internet is happy, exiting have_interenet")
        return True
    except urllib3.exceptions.NewConnectionError:
        printdebug("Internet not there, exiting have_internet")
        return False


# Function to update Google spreadsheet
def ssupdate(method):
    # Disbaling this function for now since we need to upgrade to the new Google Sheets v4 API
    return
    global OAUTHFILE
    global SPSHEET
    global lastFeed
    try:
        printdebug("Entered ssupdate function")
        json_key = json.load(open(OAUTHFILE))
        scope = ['https://spreadsheets.google.com/feeds']
        credentials = ServiceAccountCredentials.from_json_keyfile_name(OAUTHFILE, scope)
        # credentials = SignedJwtAssertionCredentials(json_key['client_email'], json_key['private_key'], scope)

        gc = gspread.authorize(credentials)
        printdebug("Authorized for ssupdate")
        ss = gc.open(SPSHEET)
        wks = gc.open(SPSHEET).sheet1
        rowcount = wks.row_count
        colcount = wks.col_count
        wks.insert_row(
            [time.strftime("%b-%d-%Y", time.localtime(lastFeed)), time.strftime("%H:%M:%S", time.localtime(lastFeed)),
             method], rowcount + 1)
        printdebug("Updated spreadsheet")
        return True

    except gspread.GSpreadException:
        return False


# Function that gets Chuck Norris jokes from the internet. It uses an HTTP GET and then a JSON parser

def getChuckNorrisQuote():
    try:
        # The database where the jokes are stored
        ICNDB = "http://api.icndb.com/jokes/random"
        http = urllib3.PoolManager(timeout=10)
        response = http.request('GET', ICNDB)
        # The response is byte encoded JSON and needs to be decoded and parsed
        # The JSON format is the following
        # {u'type': u'success', u'value' : {u'joke': 'Text of the joke', u'id': 238, u'categories': []}}
        parsed_content = json.loads(response.data.decode())
        joke = "\n\n** Random Chuck Norris Quote **:\n" + html2text.html2text(parsed_content['value']['joke'])
        printdebug(joke)
        return joke

    except:
        return "Internet not available"


# Function that gets a number trivia from the internet. It uses an HTTP GET and then a JSON parser
def getNumberTrivia():
    try:
        # The database where the trivia are stored
        NUMDB = "http://numbersapi.com/random/date?json"
        NUMDBDATEURL = "http://numbersapi.com/" + time.strftime("%m/%d", time.localtime()) + "/date?json"
        # Doing a HTTP request to get the response
        http = urllib3.PoolManager(timeout=10)
        response = http.request('GET', NUMDBDATEURL)
        # The content is byte encoded JSON and needs to be decoded and parsed
        # {u'text': u'Text of trivia', u'type' : u'trivia, u'number': <number>, u'found': True}
        parsed_content = json.loads(response.data.decode())
        trivia = "\n\n** Fact about the number " + str(parsed_content['number']) + " **\n"
        trivia = trivia + parsed_content['text']
        printdebug(trivia)
        return trivia
    except:
        return "Internet not available"


def sendreply(replyto, subject, msgBody, attach=None):
    # construct the message and send a reply
    msgHeader = "Welcome to PetFeeder!\n\n"
    msgFooter = ""
    # Add some fun things if requested
    if (CHUCKNORRIS):
        msgFooter += getChuckNorrisQuote()
    if (NUMBERTRIVIA):
        msgFooter += getNumberTrivia()

    msg = msgHeader + msgBody + msgFooter

    if attach:
        reply = petemail.create_message_with_attachment(replyto, subject, msg, attach)
    else:
        reply = petemail.create_message(replyto, subject, msg)

    petemail.send_message('me', reply)


# Function to check email
def checkmail(petemail):
    # Function will return "False" if internet is not available or if there are no "Feed" messages
    # it will respond to "When", "Pic" and "Feed" messages with an appropriate reply
    # Returns "True" is there is a Feed message

    global lastEmailCheck
    global lastFeed
    global feedInterval
    global PICFILE
    global feedreplyto
    if (have_internet()):
        ###### New Gmail API based functions ######
        messages = {}
        # Get all unread messages with known subjects from gmail
        for subject in MAILSUBJECTS:
            searchstring = 'label:unread subject:' + subject
            messages[subject] = petemail.ListMessagesMatchingQuery('me', searchstring)

        # Mark all the messages as read
        for subject in messages:
            for message in messages[subject]:
                petemail.ModifyMessage(user_id='me', msg_id=message['id'], msg_labels={'removeLabelIds': ['UNREAD']})

        if messages:
            for subject in messages:
                if (len(messages[subject]) > 0):
                    # printdebug(subject)
                    # printdebug(messages[subject][0])
                    replyto = petemail.GetFrom(user_id='me', msg_id=messages[subject][0]['id'])
                    # print(replyto)
                    # When messages handling
                    if subject == "When":
                        printdebug(
                            "Doing When action with" + str(messages[subject][0]) + "and sending reply to " + replyto)
                        if (time.time() - lastFeed) > feedInterval:
                            msgBody = "Ready to feed now!"
                        else:
                            msgBody = "The next feeding can begin on " + time.strftime("%b %d at %I:%M %P",
                                                                                       time.localtime(
                                                                                           lastFeed + feedInterval))
                        sendreply(replyto, "Thanks for the feeding query", msgBody)
                    # Pic messages handling
                    elif subject == "Pic":
                        printdebug(
                            "Doing Pic action with" + str(messages[subject][0]) + "and sending reply to " + replyto)
                        lcd.clear()
                        printlcd(0, 0, "Taking Picture")
                        if takePic():
                            lcd.clear()
                            printlcd(0, 0, "Picture Done")
                            printlcd(0, 1, "Emailing pic")
                            sendreply(replyto,
                                      "Picture taken at " + time.strftime("%b-%d, %Y at %H:%M:%S",
                                                                          time.localtime(time.time())),
                                      "Attached is the picture you requested", PICFILE)
                        else:
                            printlcd(0, 0, "Picture Error")
                            msgBody = "Could not take a picture - please make sure camera is connected and working"
                            sendreply(replyto, "Picture could not be taken", msgBody)
                    # Light messages handling
                    elif subject == "LightON":
                        ledlight("on")
                    elif subject == "LightOFF":
                        ledlight("off")
                    # Feed messages handling
                    elif subject == "Feed":
                        printdebug(
                            "Doing Feed action with" + str(messages[subject][0]) + "and sending reply to " + replyto)
                        msgBody = "The last feeding was done at " + time.strftime("%b %d at %I:%M %P",
                                                                                  time.localtime(lastFeed))
                        if (time.time() - lastFeed) > feedInterval:
                            msgBody = "\nReady to be fed, will be feeding Lucky shortly"
                        else:
                            msgBody = "\nThe next feeding can begin at " + time.strftime("%b %d at %I:%M %P",
                                                                                         time.localtime(
                                                                                             lastFeed + feedInterval))
                        sendreply(replyto, "Thanks for the feeding request", msgBody)
                        feedreplyto = replyto
                        return True
                # reply = petemail.create_message(replyto, "Reply", "Here is a reply")
                # print('Found message', message['id'])
                # petemail.send_message('me', reply)

    return False


def buttonpressed(PIN):
    # Check if the button is pressed
    global GPIO
    time.sleep(0.2)
    button_state = GPIO.input(PIN)
    if (button_state):
        return False
    else:
        return True


def remotefeedrequest():
    # At this time we are only checking for email
    # Other mechanisms for input (e.g. web interface or iOS App) is a TO-DO
    global petemail
    return checkmail(petemail)


def printlcd(row, col, LCDmesg):
    # Set the row and column for the LCD and print the message
    global logFile
    global lcd
    printdebug(LCDmesg)
    lcd.set_cursor(row, col)
    lcd.message(LCDmesg)
    pass


def feednow():
    # Run the motor for motorTime, messages in the LCD during the feeeding
    global GPIO
    global MOTORCONTROLPIN
    global motorTime
    global lastFeed
    global GMAILUSER
    global PICFILE
    global feedreplyto
    printdebug("****** Starting feeding ******")
    lcd.clear()
    printlcd(0, 0, "Feeding now.....")
    if MOTORON:
        GPIO.output(MOTORCONTROLPIN, True)
        time.sleep(motorTime)
        GPIO.output(MOTORCONTROLPIN, False)
        printlcd(0, 1, "Done!")
    time.sleep(7)  # Give it some time for the dog to come to the bowl, then take a picture
    lcd.clear()
    printlcd(0, 0, "Taking Picture")
    if takePic():
        lcd.clear()
        printlcd(0, 0, "Picture Done")
        printlcd(0, 1, "Emailing status")
        sendreply(feedreplyto,
                  "Fed Lucky at " + time.strftime("%b-%d, %Y  %H:%M:%S", time.localtime(time.time())),
                  "Lucky is fed", PICFILE)
    else:
        lcd.clear()
        printlcd(0, 0, "Picture Error")
        sendreply(feedreplyto, "Fed Lucky at " + time.strftime("%b-%d, %Y  %H:%M:%S", time.localtime(time.time())),
                  "Lucky is fed")
    time.sleep(2)
    printdebug("******* Done feeding ******")
    return time.time()


def saveLastFeed():
    global FEEDFILE
    global lastFeed
    printdebug("Got to saveLastFeed\n")
    printdebug("Got this value of lastFeed for writing into file" + FEEDFILE + "  " + str(lastFeed))
    with open(FEEDFILE, 'w') as feedFile:
        feedFile.write(str(lastFeed))
    feedFile.close()


def takePic():
    global PICFILE
    # detect if we have a camera
    camdetect = int(subprocess.check_output(["vcgencmd", "get_camera"]).decode().strip()[-1])
    if (camdetect):
        # we have a camera
        try:
            with picamera.PiCamera() as camera:
                ledlight("on")
                camera.hflip = True
                camera.vflip = True
                timenow = time.strftime("%b-%d %H:%M:%S", time.localtime(time.time()))
                camera.annotate_text = timenow
                camera.annotate_text_size = 50
                camera.resolution = (640, 480)
                camera.brightness = 55
                camera.exposure_mode = 'auto'
                camera.start_preview()
                printdebug("Capturing image...")
                camera.capture(PICFILE)
                ledlight("off")
                printdebug("Done")
            return True
        except PiCameraError:
            return False
    else:
        # did not detect camera
        return False

# The threading class
class myThread (threading.Thread):
   def __init__(self, threadID, name, delay, counter):
      threading.Thread.__init__(self)
      self.threadID = threadID
      self.name = name
      self.delay = delay
      self.counter = counter
   def run(self):
      print ("Starting " + self.name)
      pass
      print ("Exiting " + self.name)

# This is the main program, essentially runs in a continuous loop looking for button press or remote request
try:

    #### Begin initializations #########################
    ####################################################
    # Initialize the logfile
    logFile = open(LOGFILE, 'a')

    # Initialize the GPIO system
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)

    # Initialize the pin for the motor control
    GPIO.setup(MOTORCONTROLPIN, GPIO.OUT)
    GPIO.output(MOTORCONTROLPIN, False)

    # Initialize the pin for the LED light
    GPIO.setup(LEDLIGHT, GPIO.OUT)
    GPIO.output(LEDLIGHT, False)

    # Initialize the pin for the feed and reset buttons
    GPIO.setup(FEEDBUTTONPIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    GPIO.setup(RESETBUTTONPIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)

    # Initialize the LCD
    lcd = Adafruit_CharLCD(lcd_rs, lcd_en, lcd_d4, lcd_d5, lcd_d6, lcd_d7,
                           lcd_columns, lcd_rows, lcd_backlight)
    lcd.clear()

    # Initialize lastFeed
    if os.path.isfile(FEEDFILE):
        printdebug("Found the file " + FEEDFILE + " during initialization\n")
        feedFile = open(FEEDFILE, 'r')
        lastFeed = float(feedFile.read())
        printdebug(str(lastFeed))
        feedFile.close()
    else:
        printdebug("Could not find the file during initialization")
        lastFeed = time.time()
        saveLastFeed()

    try:
        petemail = mailer.Email()
    except:
        printdebug("Unable to open the google email connection")

    #### End of initializations ########################
    ####################################################

    #### The main loop ####

    while True:
    # LCD Update thread

    # Button press thread

    # Check email thread

        #### If reset button pressed, then reset the counter
        if buttonpressed(RESETBUTTONPIN):
            printdebug("Reset button is pressed")
            lcd.clear()
            printlcd(0, 0, "Resetting...   ")
            time.sleep(2)
            lastFeed = time.time() - feedInterval + 5
            saveLastFeed()

        #### Check if we are ready to feed
        if (time.time() - lastFeed) > feedInterval:
            printlcd(0, 0, time.strftime("%m/%d %I:%M:%S%P", time.localtime(time.time())))
            printlcd(0, 1, "Ready to feed   ")
            # printlcd(0,1,'Fed :' + time.strftime("%m-%d %H:%M", time.gmtime(lastFeed)))
            #### See if the button is pressed
            if buttonpressed(FEEDBUTTONPIN):
                printdebug("Got here through the feedButton")
                feedreplyto = emailid
                lastFeed = feednow()
                saveLastFeed()
                ssupdate('Button')
            #### Check if remote feed request is available
            elif remotefeedrequest():
                printdebug("Got here through the remote feed request")
                lastFeed = feednow()
                saveLastFeed()
                ssupdate('Remote')
        #### Since it is not time to feed yet, keep the countdown going
        else:
            timeToFeed = (lastFeed + feedInterval) - time.time()
            printlcd(0, 0, time.strftime("%m/%d %I:%M:%S%P", time.localtime(time.time())))
            printlcd(0, 1, 'Next:' + time.strftime("%Hh %Mm %Ss", time.gmtime(timeToFeed)))
            checkmail(petemail)
            if buttonpressed(FEEDBUTTONPIN):
                lcd.clear()
                printlcd(0, 0, "Not now, try at ")
                printlcd(0, 1, time.strftime("%b/%d %H:%M", time.localtime(lastFeed + feedInterval)))
                time.sleep(2)
        time.sleep(.6)

#### Cleaning up at the end
except KeyboardInterrupt:
    logFile.close()
    lcd.clear()
    GPIO.cleanup()

except SystemExit:
    logFile.close()
    lcd.clear()
    GPIO.cleanup()
