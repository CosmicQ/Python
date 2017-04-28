#!/usr/bin/python
#
# backup sync
#
# The backups from the production database
# is copied from Source to Destination vi SAN (clone).
# The files are then rsync'd to the destination partition.
#
# This script copies and verifies the clone and rsync
# processes and notifies the admin(s) when complete.
#
# Jason Qualkenbush - 03/17
#==========================================================
import time
import os
import sys
import re
import subprocess
import smtplib
from datetime import timedelta
from email.MIMEMultipart import MIMEMultipart
from email.MIMEText import MIMEText

# Vars
mail_to = ["me@test.com"]
#==========================================================

# Start the timer.  This is the timer for the whole process
start_time = time.time()

# Activate the volume group, just in case
os.system("/sbin/vgchange -ay vg_dst > /dev/null")

# Mount the source and destination volumes.  If mounting fails,
# back off, take a breath, try again.  Sleep times are in seconds
# so try every five minutes until success or timeout occurs.
def mount_volume(volume, mount_point):
        vol_count = 0
        while not os.path.ismount(mount_point):
                os.system('mount %s %s' % (volume, mount_point))
                vol_count = vol_count + 1
                time.sleep(3)
                if vol_count > 10:
                        time.sleep(297)
                if vol_count > 100: # This is about 8 hours.  If 8 hours pass, fail.
                        elapsed_time = time.time() - mount_start_time
                        reason = "Failed to mount volume.  Timeout occured (%s)" % (elapsed_time)
                        send_email ("Failed", reason)
                        sys.exit(1)
        return

mount_start_time = time.time()
mount_volume("/dev/mapper/vg_src-lv_src", "/srv/svol")
mount_volume("/dev/mapper vg_dst-lv_dst", "/srv/dvol")
mount_time = time.time() - mount_start_time
mount_time = int(mount_time)
mount_time = timedelta(0,mount_time)

#
# Rsync
#
rsync_start_time = time.time()

# The directory "copy" exists only if the volumes are mounted.  If we got this
# far and the volumes didn't mount, we need to fails so we don't zap the current gold since
# we are using the --delete option.
if os.path.exists("/srv/svol/copy") and os.path.exists("/srv/dvol/copy"):
        proc = subprocess.Popen(["/usr/bin/rsync -rav --dry-run --stats /srv/svol/ /srv/dvol"], stdout=subprocess.PIPE, shell=True)
        (out, err) = proc.communicate()
        xfer_files = out
        os.system("/usr/bin/rsync -ra --delete /srv/svol/ /srv/dvol")
else:
        # The directory we want to sync isn't there.  Spit out some debug info and bail
        proc = subprocess.Popen(["/bin/df"], stdout=subprocess.PIPE, shell=True)
        (out, err) = proc.communicate()
        debug = out
        message = "Rsync source/dest suspect.  Please check\n\n%s" % (debug)
        send_email ("Failed", message)
        sys.exit(1)

rsync_time = time.time() - rsync_start_time
rsync_time = int(rsync_time)
rsync_time = timedelta(0,rsync_time)

#
# Unmount source
#
def unmount_volume(mount_point):
        vol_count = 0
        while os.path.ismount(mount_point):
                time.sleep(3)
                os.system('umount %s' % (mount_point))
                vol_count = vol_count + 1
                if vol_count > 10:
                        time.sleep(297)
                if vol_count > 30:
                                proc = subprocess.Popen(["/usr/sbin/lsof |grep svol"], stdout=subprocess.PIPE, shell=True)
                                (out, err) = proc.communicate()
                                debug = out
                                message = "Failed to unmount volume. Timeout Occured\n\n%s" % (debug)
                                send_email ("Failed", message)
                                sys.exit(1)
        return

unmount_start_time = time.time()
unmount_volume("/srv/svol")
unmount_time = time.time() - unmount_start_time
unmount_time = int(unmount_time)
unmount_time = timedelta(0,unmount_time)

# End timer
total_time = time.time() - start_time
total_time = int(total_time)
total_time = timedelta(0,total_time)

# Need to extract the number of files and number of bytes that were transferred in the 
# rsync into easy human forms.  First we need to extract the files and bytes from "xfer_files"
# and then add that to the "info" variable, for the summary email
def humanbytes(B):
        B = float(B)
        KB = float(1024)
        MB = float(KB ** 2) # 1,048,576
        GB = float(KB ** 3) # 1,073,741,824
        TB = float(KB ** 4) # 1,099,511,627,776

        if B < KB:
                return '{0} {1}'.format(B,'Bytes' if 0 == B > 1 else 'Byte')
        elif KB <= B < MB:
                return '{0:.2f} KB'.format(B/KB)
        elif MB <= B < GB:
                return '{0:.2f} MB'.format(B/MB)
        elif GB <= B < TB:
                return '{0:.2f} GB'.format(B/GB)
        elif TB <= B:
                return '{0:.2f} TB'.format(B/TB)

for line in xfer_files.split('\n'):
        if re.search(r'Number of files transferred:', line):
                tot_files = line
        elif re.search(r'Total transferred file size:', line):
                byte_size = line
                splitted = byte_size.split()
                byte_size = splitted[4]
                tot_size = humanbytes(byte_size)

# Email the report!  Summary in the body, and details in the attachment
def send_email(status, reason, details):
        server = smtplib.SMTP('localhost', 25)

        msg = MIMEMultipart()
        msg['From']    = "rsync_job@server.test.com"
        msg['To']      = ", ".join(mail_to)
        msg['Subject'] = "Copy %s" % status

        body = reason

        # We don't need the rsync output in the email body all the time.  Just
        # add it as it an attachment if people really want to look at it.
        # The message body should be simple, short, and summary only.
        if details:
                attachment = MIMEText(details)
                attachment.add_header('Content-Disposition', 'attachment', filename=filename)
                msg.attach(attachment)

        msg.attach(MIMEText(body, 'plain'))
        text = msg.as_string()
        server.sendmail("rsync_monitor@server.test.com", mail_to, msg.as_string())
        server.quit()

summary  = "Copy summary...\n\n\t%s\n\t     Total data transferred: %s\n\tTotal execution time: %s\n" % (tot_files, tot_size, total_time)
filename="rsync_details.txt"
deets = "Checkpoint Times...\n\n\t  Mount time: %s\n\t  Rsync time: %s\n\tUnmount Time: %s\n\nRsync Details...\n\n%s" % (mount_time, rsync_time, unmount_time, xfer_files)
send_email("Completed", summary, deets)