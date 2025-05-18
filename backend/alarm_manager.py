from apscheduler.schedulers.background import BackgroundScheduler
def start_alarms(email):
    scheduler = BackgroundScheduler()
    scheduler.add_job(lambda: print(f"Email {email}: Weekly tasks due!"), 'interval', weeks=1)
    scheduler.start()
