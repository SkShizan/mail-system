import smtplib, ssl

context = ssl.create_default_context()

server = smtplib.SMTP("smtp.gmail.com", 587, timeout=15)
server.set_debuglevel(1)
server.ehlo()
server.starttls(context=context)
server.ehlo()
server.login("shizankhan011@gmail.com", "kjqshtanosrifokr")
server.sendmail(
    "YOUR_EMAIL@gmail.com",
    "YOUR_EMAIL@gmail.com",
    "Subject: Test\n\nHello"
)
server.quit()
