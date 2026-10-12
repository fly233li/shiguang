"""Deterministic sample data for visual QA, always used in a temporary DB."""
from datetime import date, datetime, time, timedelta


def seed_demo(store):
    now = datetime.now().timestamp()
    apps = [("Code.exe","Visual Studio Code"),("msedge.exe","Microsoft Edge"),
            ("WeChat.exe","微信"),("Figma.exe","Figma"),("Notion.exe","Notion")]
    for offset in range(29,-1,-1):
        day = date.today()-timedelta(days=offset)
        for h in range(9,19):
            start = datetime.combine(day,time(h)).timestamp()
            if start+3600 > now:
                continue
            key,name = apps[(h+offset)%len(apps)]
            active = [2400,1980,1620,2820,2700][(h+offset)%5]
            store.add_interval(start,start+active,"active",key,name,"C:\\Apps\\"+key)
            store.add_interval(start+active,start+3600,"idle" if h%3 else "locked")
