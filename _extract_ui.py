import pathlib, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
text = pathlib.Path("assets/index-CtjlL1Yw.js").read_text(encoding="utf-8", errors="ignore")
needles = [
    '__name:"CheckActivity"',
    '__name:"check-activity"',
    'MessageFromModerator',
    'FinishedClear',
    'type:"Finished"',
    'name-history',
    'court-commands',
    'last_moved_seconds',
    'нет на месте',
    'is_pm',
    '[PM]',
    'browseBatchLoader.load',
]
for n in needles:
    i = text.find(n)
    print(f"==== {n} idx={i} ====")
    if i >= 0:
        print(text[max(0,i-80):i+400])
        print()
