from ask import ask
for m in ["qwen3:4b-instruct-2507-q4_K_M", "llama3.2:3b"]:
       print("=====", m)
       ask("What is a half step?", model=m)
       ask("How do I tune by ear?", model=m)
       ask("my fingers hurt, is that normal?", model=m)