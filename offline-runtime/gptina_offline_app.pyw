#!/usr/bin/env python3
from __future__ import annotations
import json, os, socket, subprocess, sys, threading, time, webbrowser
from pathlib import Path
from tkinter import BOTH, END, LEFT, RIGHT, X, Button, Entry, Frame, Label, StringVar, Text, Tk, filedialog, messagebox
from urllib.request import Request, urlopen

SCRIPT_DIR = Path(sys.executable).resolve().parent if getattr(sys,"frozen",False) else Path(__file__).resolve().parent
ENGINE_EXE = SCRIPT_DIR / "engine" / "llama-server.exe"
MEMORY_SCRIPT = SCRIPT_DIR / "gptina_memory_server.py"
CHAT_SCRIPT = SCRIPT_DIR / "gptina_chat_bridge.py"
INSTALLER_SCRIPT = SCRIPT_DIR / "install_llama_engine.py"
LOCAL_CONFIG = SCRIPT_DIR / ".gptina_app_config.json"
LOG_DIR = SCRIPT_DIR / "logs"
PORT_ENGINE, PORT_MEMORY, PORT_CHAT = 5001, 8765, 8766
DEFAULTS={"model_path":"","threads":"2","context":"1024","predict":"160"}

def http_ok(url, timeout=1.0):
    try:
        with urlopen(Request(url,headers={"Accept":"application/json"}),timeout=timeout) as r:
            return 200 <= r.status < 300
    except Exception:
        return False

def port_open(port):
    try:
        with socket.create_connection(("127.0.0.1",port),timeout=.4): return True
    except OSError: return False

def wait_http(url, seconds):
    end=time.time()+seconds
    while time.time()<end:
        if http_ok(url): return True
        time.sleep(.35)
    return False

def detect_models():
    roots=[SCRIPT_DIR.parent/"models",Path.home()/"Downloads"/"GPTina offline",Path.home()/"Downloads"]
    found=[]
    for root in roots:
        if not root.exists(): continue
        try:
            it=root.glob("*.gguf") if root.name=="Downloads" else root.rglob("*.gguf")
            found.extend([p for p in it if p.is_file()])
        except Exception: pass
    return sorted(set(found),key=lambda p:p.stat().st_mtime,reverse=True)

def load_cfg():
    cfg=dict(DEFAULTS)
    if LOCAL_CONFIG.exists():
        try: cfg.update(json.loads(LOCAL_CONFIG.read_text(encoding="utf-8")))
        except Exception: pass
    if not cfg["model_path"]:
        m=detect_models()
        if m: cfg["model_path"]=str(m[0])
    return {k:str(v) for k,v in cfg.items()}

def save_cfg(cfg):
    LOCAL_CONFIG.write_text(json.dumps(cfg,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

def pyexe():
    return sys.executable

class App:
    def __init__(self,root):
        self.root=root; self.root.title("GPTina Offline"); self.root.geometry("720x500")
        self.procs=[]; self.handles=[]; c=load_cfg()
        box=Frame(root,padx=14,pady=14); box.pack(fill=BOTH,expand=True)
        Label(box,text="GPTina Offline",font=("Segoe UI",18,"bold")).pack(anchor="w")
        Label(box,text="Motore locale + memoria + chat, avviati insieme.").pack(anchor="w",pady=(0,14))
        row=Frame(box); row.pack(fill=X,pady=5)
        Label(row,text="Modello GGUF:",width=14,anchor="w").pack(side=LEFT)
        self.model=StringVar(value=c["model_path"]); Entry(row,textvariable=self.model).pack(side=LEFT,fill=X,expand=True,padx=(0,8))
        Button(row,text="Sfoglia…",command=self.browse).pack(side=RIGHT)
        row=Frame(box); row.pack(fill=X,pady=5)
        Label(row,text="Thread:").pack(side=LEFT); self.threads=StringVar(value=c["threads"]); Entry(row,width=5,textvariable=self.threads).pack(side=LEFT,padx=(4,14))
        Label(row,text="Context:").pack(side=LEFT); self.context=StringVar(value=c["context"]); Entry(row,width=7,textvariable=self.context).pack(side=LEFT,padx=(4,14))
        Label(row,text="Max risposta:").pack(side=LEFT); self.predict=StringVar(value=c["predict"]); Entry(row,width=7,textvariable=self.predict).pack(side=LEFT,padx=(4,14))
        erow=Frame(box); erow.pack(fill=X,pady=(8,4))
        self.engine=Label(erow,text=""); self.engine.pack(side=LEFT); self.refresh()
        Button(erow,text="Installa / aggiorna motore",command=self.install_engine).pack(side=RIGHT)
        row=Frame(box); row.pack(fill=X,pady=8)
        self.startb=Button(row,text="AVVIA GPTINA",height=2,command=self.start); self.startb.pack(side=LEFT,fill=X,expand=True,padx=(0,6))
        Button(row,text="Apri chat",height=2,command=lambda:webbrowser.open("http://127.0.0.1:8766")).pack(side=LEFT,padx=6)
        Button(row,text="Ferma",height=2,command=self.stop).pack(side=RIGHT,padx=(6,0))
        self.status=Label(box,text="Pronta.",anchor="w"); self.status.pack(fill=X)
        self.log=Text(box,height=15,wrap="word"); self.log.pack(fill=BOTH,expand=True,pady=(8,0))
        self.write("Profilo iniziale: 2 thread, context 1024, output 160 token.")
        self.write("Il primo benchmark confronterà 2 e 4 thread.")
        root.protocol("WM_DELETE_WINDOW",self.close)

    def write(self,t):
        self.log.insert(END,str(t).rstrip()+"\n"); self.log.see(END); self.root.update_idletasks()
    def setstatus(self,t): self.status.config(text=t); self.root.update_idletasks()
    def refresh(self): self.engine.config(text="Motore: installato" if ENGINE_EXE.exists() else "Motore: manca offline-runtime\\engine\\llama-server.exe")
    def browse(self):
        p=filedialog.askopenfilename(title="Scegli modello",initialdir=str(Path.home()/"Downloads"),filetypes=[("GGUF","*.gguf"),("Tutti","*.*")])
        if p:self.model.set(p)
    def install_engine(self):
        if not INSTALLER_SCRIPT.exists():
            messagebox.showerror("GPTina Offline","Installer del motore non trovato.")
            return
        def work():
            self.setstatus("Installazione motore…")
            self.write("Scarico il runtime llama.cpp preparato per questa app…")
            try:
                p=subprocess.run([pyexe(),str(INSTALLER_SCRIPT)],cwd=str(SCRIPT_DIR),capture_output=True,text=True,timeout=300)
                if p.stdout:
                    for line in p.stdout.splitlines(): self.write(line)
                if p.stderr:
                    for line in p.stderr.splitlines(): self.write(line)
                if p.returncode!=0 or not ENGINE_EXE.exists():
                    raise RuntimeError(f"Installazione fallita (exit {p.returncode}).")
                self.refresh(); self.setstatus("Motore pronto."); self.write("Motore installato.")
            except Exception as e:
                self.write("ERRORE installazione: "+str(e)); self.setstatus("Installazione fallita."); messagebox.showerror("GPTina Offline",str(e))
        threading.Thread(target=work,daemon=True).start()

    def validate(self):
        m=Path(self.model.get().strip())
        if not m.is_file() or m.suffix.lower()!=".gguf": raise ValueError("Seleziona un modello .gguf valido.")
        if not ENGINE_EXE.is_file(): raise ValueError("Manca llama-server.exe nella cartella offline-runtime\\engine.")
        t=int(self.threads.get()); c=int(self.context.get()); n=int(self.predict.get())
        if not 1<=t<=8: raise ValueError("Thread: usa un valore da 1 a 8.")
        if not 512<=c<=8192: raise ValueError("Context: usa un valore da 512 a 8192.")
        if not 32<=n<=1024: raise ValueError("Max risposta: usa un valore da 32 a 1024.")
        return m,t,c,n
    def spawn(self,cmd,name):
        LOG_DIR.mkdir(parents=True,exist_ok=True)
        h=open(LOG_DIR/name,"a",encoding="utf-8",buffering=1); self.handles.append(h)
        kw={"cwd":str(SCRIPT_DIR),"stdout":h,"stderr":subprocess.STDOUT}
        if os.name=="nt": kw["creationflags"]=getattr(subprocess,"CREATE_NO_WINDOW",0)
        p=subprocess.Popen(cmd,**kw); self.procs.append(p); return p
    def start(self):
        try:m,t,c,n=self.validate()
        except Exception as e: messagebox.showerror("GPTina Offline",str(e)); return
        if port_open(PORT_ENGINE) and not http_ok(f"http://127.0.0.1:{PORT_ENGINE}/health"):
            messagebox.showerror("GPTina Offline","La porta 5001 è occupata. Chiudi KoboldCpp e riprova."); return
        save_cfg({"model_path":str(m),"threads":str(t),"context":str(c),"predict":str(n)})
        self.startb.config(state="disabled")
        threading.Thread(target=self.worker,args=(m,t,c,n),daemon=True).start()
    def worker(self,m,t,c,n):
        try:
            self.setstatus("Avvio motore…")
            if not http_ok("http://127.0.0.1:5001/health"):
                self.write(f"Motore: {m.name} · {t} thread · ctx {c}")
                self.spawn([str(ENGINE_EXE),"-m",str(m),"--host","127.0.0.1","--port","5001","-t",str(t),"-tb",str(t),"-c",str(c),"-n",str(n),"-b","256","-ub","128","-ngl","0","--flash-attn","off"],"engine.log")
                if not wait_http("http://127.0.0.1:5001/health",180): raise RuntimeError("Motore non pronto. Guarda logs\\engine.log")
            self.write("Motore: OK")
            self.setstatus("Avvio memoria…")
            if not http_ok("http://127.0.0.1:8765/health"):
                self.spawn([pyexe(),str(MEMORY_SCRIPT),"--host","127.0.0.1","--port","8765"],"memory.log")
                if not wait_http("http://127.0.0.1:8765/health",30): raise RuntimeError("Memory runtime non pronto.")
            self.write("Memoria: OK")
            self.setstatus("Avvio chat…")
            if not http_ok("http://127.0.0.1:8766/health"):
                self.spawn([pyexe(),str(CHAT_SCRIPT),"--host","127.0.0.1","--port","8766"],"chat.log")
                if not wait_http("http://127.0.0.1:8766/health",30): raise RuntimeError("Chat bridge non pronto.")
            self.write("Chat: OK"); self.setstatus("GPTina Offline pronta."); webbrowser.open("http://127.0.0.1:8766")
        except Exception as e:
            self.write("ERRORE: "+str(e)); self.setstatus("Avvio fallito."); messagebox.showerror("GPTina Offline",str(e))
        finally:self.startb.config(state="normal")
    def stop(self):
        for p in reversed(self.procs):
            try:
                if p.poll() is None:p.terminate()
            except Exception:pass
        self.procs.clear()
        for h in self.handles:
            try:h.close()
            except Exception:pass
        self.handles.clear(); self.write("Processi avviati dall'app fermati."); self.setstatus("Fermata.")
    def close(self):
        if self.procs and messagebox.askyesno("GPTina Offline","Fermare anche i processi locali?"): self.stop()
        self.root.destroy()

def main():
    r=Tk(); App(r); r.mainloop()
if __name__=="__main__": main()
