import numpy as np
from scipy.signal import butter, lfilter, fftconvolve
from scipy.io import wavfile
import os, sys

SR = 44100
DURATION = 60
OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))
os.makedirs(OUTPUT_DIR, exist_ok=True)

def note_freq(n):
    notes = {'C':0,'D':2,'E':4,'F':5,'G':7,'A':9,'B':11}
    midi = 12*(int(n[-1])+1)+notes[n[0]]
    return 440.0*(2**((midi-69)/12.0))

def make_env(length, atk=0.01, dec=0.05, sus=0.7, rel=0.1):
    env = np.ones(length)
    a=max(int(atk*length),1); d=max(int(dec*length),1); r=max(int(rel*length),1)
    env[:a]=np.linspace(0,1,a)
    s,e=a,min(a+d,length)
    if e>s: env[s:e]=np.linspace(1,sus,e-s)
    ss,se=a+d,max(length-r,a+d)
    if ss<se: env[ss:se]=sus
    if r>0 and length>r: env[-r:]=np.linspace(sus,0,r)
    return env

def lpf(sig,cut,sr=SR,order=4):
    b,a=butter(order,min(cut/(0.5*sr),0.99),btype='low'); return lfilter(b,a,sig)

def hpf(sig,cut,sr=SR,order=2):
    b,a=butter(order,max(cut/(0.5*sr),0.01),btype='high'); return lfilter(b,a,sig)

def bpf(sig,lo,hi,sr=SR,order=2):
    nyq=0.5*sr; ln,hn=max(lo/nyq,0.01),min(hi/nyq,0.99)
    if ln>=hn: return sig
    b,a=butter(order,[ln,hn],btype='band'); return lfilter(b,a,sig)

def rev(sig,decay=0.3,length=0.8,sr=SR):
    il=int(sr*length); rng=np.random.RandomState(42)
    ir=rng.randn(il)*np.exp(-np.linspace(0,8,il)); ir[0]=1.0; ir*=decay; ir[0]=1.0
    return 0.6*sig+0.4*fftconvolve(sig,ir)[:len(sig)]

def sclip(sig,th=0.8): return np.tanh(sig/th)*th

def to_stereo(mono,w=0.3):
    dl=int(0.0003*SR*w*10)
    return np.column_stack([mono.copy(), lpf(np.roll(mono,dl),12000)])

def norm(sig,pk=0.85):
    mx=np.max(np.abs(sig)); return sig*(pk/mx) if mx>0 else sig

def save_wav(fn,audio,sr=SR):
    audio=np.clip(audio,-1.0,1.0)
    p=os.path.join(OUTPUT_DIR,fn)
    wavfile.write(p,sr,(audio*32767).astype(np.int16))
    mb=os.path.getsize(p)/(1024*1024)
    print(f"  Saved: {fn} ({mb:.1f} MB)")

def pl(tgt,smp,pos,vol=1.0):
    if 0<=pos<len(tgt):
        end=min(pos+len(smp),len(tgt)); tgt[pos:end]+=smp[:end-pos]*vol

def syn_pad(freq,dur,sr=SR,bright=0.5,det=0.003):
    t=np.arange(int(sr*dur))/sr; sig=np.zeros_like(t)
    for d in [-det,-det/2,0,det/2,det]:
        f=freq*(1+d); sig+=np.sin(2*np.pi*f*t)+0.5*np.sin(2*np.pi*f*2*t)+0.25*np.sin(2*np.pi*f*3*t)
    return lpf(sig/5,800+bright*4000,sr)*make_env(len(sig),0.15,0.1,0.8,0.2)

def syn_bass(freq,dur,sr=SR,sty='warm'):
    t=np.arange(int(sr*dur))/sr
    if sty=='warm':
        sig=np.sin(2*np.pi*freq*t)+0.6*np.sin(2*np.pi*freq*2*t)+0.2*np.sin(2*np.pi*freq*3*t); sig=lpf(sig,600,sr)
    elif sty=='sub':
        sig=np.sin(2*np.pi*freq*t)+0.3*np.sin(2*np.pi*freq*2*t); sig=lpf(sig,300,sr)
    else:
        sig=np.sin(2*np.pi*freq*t)+0.8*np.sin(2*np.pi*freq*2*t)+0.5*np.sin(2*np.pi*freq*3*t)+0.3*np.sin(2*np.pi*freq*4*t)
        sig=lpf(sig,1200,sr)
    return sig*make_env(len(sig),0.005,0.2,0.4,0.1)

def syn_keys(freq,dur,sr=SR,tone='warm'):
    t=np.arange(int(sr*dur))/sr
    mr=7.0 if tone=='warm' else 3.5; mi=2.0 if tone=='warm' else 3.5
    mod=mi*np.sin(2*np.pi*freq*mr*t)*np.exp(-t*4)
    sig=np.sin(2*np.pi*freq*t+mod)+0.3*np.sin(2*np.pi*freq*2*t)
    return lpf(sig,3000 if tone=='warm' else 5000,sr)*make_env(len(sig),0.005,0.3,0.3,0.15)

def dr_kick(sr=SR):
    t=np.arange(int(0.3*sr))/sr
    sig=np.sin(np.cumsum(2*np.pi*(150*np.exp(-t*30)+50)/sr))*np.exp(-t*12)
    cl=int(0.003*sr); sig[:cl]+=np.random.randn(cl)*0.5*np.exp(-np.linspace(0,10,cl))
    return sig

def dr_snare(sr=SR,tight=False):
    ln=int(0.25*sr); t=np.arange(ln)/sr
    tone=np.sin(2*np.pi*200*t)*np.exp(-t*20); noise=np.random.randn(ln)
    if tight: noise=bpf(noise,2000,8000,sr)*np.exp(-t*25)
    else: noise=bpf(noise,1000,7000,sr)*np.exp(-t*15)
    return 0.5*tone+0.5*noise

def dr_hh(sr=SR,op=False):
    ln=int((0.3 if op else 0.08)*sr); t=np.arange(ln)/sr
    return hpf(np.random.randn(ln),6000,sr)*np.exp(-t*(8 if op else 40))*0.3

def dr_rim(sr=SR):
    ln=int(0.05*sr); t=np.arange(ln)/sr
    return np.sin(2*np.pi*800*t)*np.exp(-t*60)+hpf(np.random.randn(ln),3000,sr)*np.exp(-t*80)*0.3

def vinyl(dur,sr=SR,intensity=0.015):
    ln=int(sr*dur); hiss=bpf(np.random.randn(ln)*intensity*0.3,500,5000,sr)
    crk=np.zeros(ln)
    for pos in np.random.randint(0,ln,int(dur*15)):
        cl=np.random.randint(5,50); end=min(pos+cl,ln)
        crk[pos:end]=np.random.randn(end-pos)*intensity*np.exp(-np.linspace(0,5,end-pos))
    return hiss+crk

LOFI=[(['C3','E3','G3','B3'],'C2'),(['D3','F3','A3','C4'],'D2'),
      (['E3','G3','B3','D4'],'E2'),(['F3','A3','C4','E4'],'F2')]
UPBT=[(['C3','E3','G3'],'C2'),(['G3','B3','D4'],'G2'),
      (['A3','C4','E4'],'A2'),(['F3','A3','C4'],'F2')]
CHLL=[(['A2','C3','E3','G3'],'A1'),(['F2','A2','C3','E3'],'F1'),
      (['C3','E3','G3','B3'],'C2'),(['G2','B2','D3','F3'],'G1')]

def mk_drums(pt,bpm,dur,sr=SR):
    bs=int(60/bpm*sr); sx=bs//4; tot=int(sr*dur); dr=np.zeros(tot)
    kick,snare,hc,ho,rim=dr_kick(sr),dr_snare(sr,tight=(pt=='upbeat')),dr_hh(sr),dr_hh(sr,True),dr_rim(sr)
    bar=bs*4; pos=0
    while pos<tot:
        for b in range(16):
            sp=pos+b*sx
            if sp>=tot: break
            if pt=='lofi':
                sp+=np.random.randint(-max(int(sx*0.05),1),max(int(sx*0.05),1)+1)
                if sp<0 or sp>=tot: continue
                if b in [0,6,10]: pl(dr,kick,sp,0.7)
                if b in [4,12]: pl(dr,snare,sp,0.5)
                if b%2==0: pl(dr,hc,sp,0.2+0.1*np.random.random())
                elif np.random.random()>0.4: pl(dr,hc,sp+int(sx*0.15),0.15)
            elif pt=='upbeat':
                if b%4==0: pl(dr,kick,sp,0.8)
                if b in [4,12]: pl(dr,snare,sp,0.6)
                if b%2==0: pl(dr,hc,sp,0.25)
                elif np.random.random()>0.5: pl(dr,hc,sp,0.15)
                if b in [6,14] and np.random.random()>0.6: pl(dr,ho,sp,0.2)
            elif pt=='chill':
                if b in [0,8]: pl(dr,kick,sp,0.5)
                if b in [4,12]: pl(dr,rim,sp,0.3)
                if b%4==0: pl(dr,hc,sp,0.12)
                elif b%4==2 and np.random.random()>0.3: pl(dr,hc,sp,0.08)
        pos+=bar
    return dr

def gen_lofi():
    print("[1/3] Generating Lo-Fi track...")
    bpm,bd=75,60.0/75; tot=int(SR*DURATION)
    ch,ky,bs=np.zeros(tot),np.zeros(tot),np.zeros(tot)
    t,ci=0,0
    while t<DURATION:
        cn,bn=LOFI[ci%4]; rem=min(bd*8,DURATION-t)
        for n in cn:
            p=syn_pad(note_freq(n),rem,bright=0.2,det=0.004); s=int(t*SR)
            if s+len(p)<=tot: ch[s:s+len(p)]+=p*0.15
        for i,n in enumerate(cn):
            nt=t+i*bd*0.5
            if nt<DURATION:
                k=syn_keys(note_freq(n),bd*1.5,tone='warm'); s=int(nt*SR)
                if s+len(k)<=tot: ky[s:s+len(k)]+=k*0.2
        bf=note_freq(bn)
        b=syn_bass(bf,bd*2,sty='warm'); s=int(t*SR)
        if s+len(b)<=tot: bs[s:s+len(b)]+=b*0.35
        b2t=t+bd*4+bd*2
        if b2t<DURATION:
            b2=syn_bass(bf*2,bd,sty='warm'); s=int(b2t*SR)
            if s+len(b2)<=tot: bs[s:s+len(b2)]+=b2*0.2
        t+=bd*8; ci+=1
    print("  Drums + vinyl crackle...")
    mix=ch+ky+bs+mk_drums('lofi',bpm,DURATION)+vinyl(DURATION,intensity=0.012)
    print("  Mixing & effects...")
    mix=norm(sclip(rev(lpf(mix,8000),0.25,1.0),0.7),0.82)
    st=to_stereo(mix,0.4)
    fi,fo=np.linspace(0,1,SR*2),np.linspace(1,0,SR*3)
    st[:len(fi),0]*=fi; st[:len(fi),1]*=fi
    st[-len(fo):,0]*=fo; st[-len(fo):,1]*=fo
    save_wav('lofi.wav',st)
    print("  Lo-Fi complete!")

def gen_upbeat():
    print("[2/3] Generating Upbeat track...")
    bpm,bd=120,60.0/120; tot=int(SR*DURATION)
    ch,ky,bs=np.zeros(tot),np.zeros(tot),np.zeros(tot)
    t,ci=0,0
    while t<DURATION:
        cn,bn=UPBT[ci%4]; rem=min(bd*4,DURATION-t)
        for n in cn:
            p=syn_pad(note_freq(n),rem,bright=0.7,det=0.002); s=int(t*SR)
            if s+len(p)<=tot: ch[s:s+len(p)]+=p*0.12
        for beat in range(8):
            ni=beat%len(cn); nt=t+beat*bd*0.5
            if nt<DURATION:
                k=syn_keys(note_freq(cn[ni]),bd*0.4,tone='bright'); s=int(nt*SR)
                if s+len(k)<=tot: ky[s:s+len(k)]+=k*(0.2 if beat%2==0 else 0.12)
        bf=note_freq(bn)
        for beat in range(4):
            bt=t+beat*bd
            if bt<DURATION:
                if beat in [0,2]: ba=syn_bass(bf,bd*0.8,sty='plucky'); v=0.4
                else: ba=syn_bass(bf*2,bd*0.5,sty='plucky'); v=0.25
                s=int(bt*SR)
                if s+len(ba)<=tot: bs[s:s+len(ba)]+=ba*v
        t+=bd*4; ci+=1
    print("  Drums...")
    mix=ch+ky+bs+mk_drums('upbeat',bpm,DURATION)
    print("  Mixing & effects...")
    mix=norm(sclip(rev(lpf(mix,14000),0.15,0.5),0.8),0.85)
    st=to_stereo(mix,0.5)
    fi,fo=np.linspace(0,1,SR*1),np.linspace(1,0,SR*2)
    st[:len(fi),0]*=fi; st[:len(fi),1]*=fi
    st[-len(fo):,0]*=fo; st[-len(fo):,1]*=fo
    save_wav('upbeat.wav',st)
    print("  Upbeat complete!")

def gen_chill():
    print("[3/3] Generating Chill track...")
    bpm,bd=85,60.0/85; tot=int(SR*DURATION)
    pd,ky,bs=np.zeros(tot),np.zeros(tot),np.zeros(tot)
    t,ci=0,0
    while t<DURATION:
        cn,bn=CHLL[ci%4]; rem=min(bd*8,DURATION-t)
        for n in cn:
            p=syn_pad(note_freq(n),rem,bright=0.3,det=0.006); s=int(t*SR)
            if s+len(p)<=tot: pd[s:s+len(p)]+=p*0.18
        for i,n in enumerate(cn*2):
            nt=t+i*bd*1.5
            if nt<DURATION:
                k=syn_keys(note_freq(n),bd*3,tone='warm'); s=int(nt*SR)
                if s+len(k)<=tot: ky[s:s+len(k)]+=k*0.12
        bf=note_freq(bn)
        ba=syn_bass(bf,bd*8*0.8,sty='sub'); s=int(t*SR)
        if s+len(ba)<=tot: bs[s:s+len(ba)]+=ba*0.3
        t+=bd*8; ci+=1
    print("  Texture + drums...")
    noise=bpf(np.random.randn(tot)*0.02,200,3000)
    lfo=0.5+0.5*np.sin(2*np.pi*0.1*np.arange(tot)/SR)
    mix=pd+ky+bs+mk_drums('chill',bpm,DURATION)+noise*lfo
    print("  Mixing & effects...")
    mix=norm(sclip(rev(lpf(mix,9000),0.4,1.5),0.65),0.80)
    st=to_stereo(mix,0.6)
    fi,fo=np.linspace(0,1,SR*3),np.linspace(1,0,SR*4)
    st[:len(fi),0]*=fi; st[:len(fi),1]*=fi
    st[-len(fo):,0]*=fo; st[-len(fo):,1]*=fo
    save_wav('chill.wav',st)
    print("  Chill complete!")

if __name__=='__main__':
    print("="*60)
    print("  BGM Generator - Procedural Music Synthesis")
    print(f"  Output: {OUTPUT_DIR}")
    print(f"  Duration: {DURATION}s | Sample Rate: {SR}Hz | Stereo")
    print("="*60)
    gen_lofi()
    gen_upbeat()
    gen_chill()
    print("="*60)
    print("  All 3 BGM tracks generated successfully!")
    print("="*60)
    for fn in ['lofi.wav','upbeat.wav','chill.wav']:
        p=os.path.join(OUTPUT_DIR,fn)
        if os.path.exists(p):
            print(f"  {fn}: {os.path.getsize(p)/(1024*1024):.1f} MB")
