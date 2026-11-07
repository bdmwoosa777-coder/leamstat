"""Generic one-shot Xbox button/trigger tester. No mouse or keyboard injection."""
import ctypes as C
import os
import re
import time

CONTROLS={'A':0x1000,'X':0x4000,'Y':0x8000,'B':0x2000,
          'RB':0x0200,'RT':None,'LB':0x0100,'LT':None}


def press_control(pad,vg,name):
    """Always start neutral; clean up even if the driver applied a failing report."""
    try:
        pad.reset()
        if name=='RT':pad.right_trigger(value=255)
        elif name=='LT':pad.left_trigger(value=255)
        else:pad.press_button(button=vg.XUSB_BUTTON(CONTROLS[name]))
        pad.update()
    except BaseException:
        try:pad.reset();pad.update()
        except Exception:pass
        raise


class App:
    def __init__(self,root):
        import tkinter as tk
        from tkinter import ttk
        from tkinter.scrolledtext import ScrolledText
        self.root=root;self.pad=None;self.vg=None;self.phase='idle';self.deadline=0
        self.control=None;self.seen=set();self.last_second=None;self.closed=False
        self.u=C.WinDLL('user32')
        self.u.GetForegroundWindow.restype=C.c_void_p
        self.u.GetWindowTextW.argtypes=[C.c_void_p,C.c_wchar_p,C.c_int]
        self.u.GetAsyncKeyState.argtypes=[C.c_int];self.u.GetAsyncKeyState.restype=C.c_short
        self.x=C.WinDLL('xinput1_4.dll')
        self.x.XInputGetState.argtypes=[C.c_uint32,C.c_void_p]
        self.x.XInputGetState.restype=C.c_uint32
        root.title('Gamepad Buttons Test');root.geometry('800x520')
        root.protocol('WM_DELETE_WINDOW',self.close)
        panel=ttk.Frame(root,padding=16);panel.pack(fill='both',expand=True)
        ttk.Label(panel,text='Одно нажатие выбранной кнопки Xbox',font=('Segoe UI',13,'bold')).pack(anchor='w')
        ttk.Label(panel,wraplength=750,text='Подключите виртуальный Xbox, откройте нужное окно игры. Выберите кнопку, запустите тест и за 8 секунд наведите курсор. Автоматического перебора кнопок нет.').pack(anchor='w',pady=10)
        ttk.Button(panel,text='1. Подключить виртуальный Xbox',command=self.connect).pack(anchor='w')
        row=ttk.Frame(panel);row.pack(fill='x',pady=14)
        ttk.Label(row,text='Кнопка:').pack(side='left')
        self.choice=tk.StringVar(value='X')
        self.combo=ttk.Combobox(row,textvariable=self.choice,values=list(CONTROLS),state='readonly',width=8)
        self.combo.pack(side='left',padx=8)
        self.button=ttk.Button(row,text='2. Одно нажатие через 8 секунд',command=self.start,state='disabled')
        self.button.pack(side='left',padx=8)
        ttk.Button(row,text='СТОП / отпустить',command=self.cancel).pack(side='left')
        ttk.Label(panel,text='Esc отменяет тест. В момент нажатия должно быть активно окно AION2.').pack(anchor='w')
        self.status=tk.StringVar(value='Не подключено')
        ttk.Label(panel,textvariable=self.status).pack(anchor='w',pady=10)
        self.text=ScrolledText(panel,height=15,wrap='word',state='disabled');self.text.pack(fill='both',expand=True)
        self.log('Нужны установленный ViGEmBus и пакет vgamepad. Эта программа ничего не устанавливает.')
        root.after(20,self.tick)

    def log(self,text):
        self.text.configure(state='normal');self.text.insert('end',time.strftime('%H:%M:%S ')+text+'\n')
        self.text.see('end');self.text.configure(state='disabled')

    def connect(self):
        if self.pad:return
        try:
            import vgamepad as vg
            self.vg=vg;self.pad=vg.VX360Gamepad();self.neutral()
            self.button.configure(state='normal');self.status.set('Xbox подключён, можно запускать игру')
            self.log('Подключён Xbox 360. Физический F710 лучше отключить, чтобы не было второго контроллера.')
        except Exception as exc:
            self.pad=None;self.log('Ошибка подключения: '+str(exc))

    def neutral(self):
        if self.pad:self.pad.reset();self.pad.update()

    def start(self):
        if not self.pad or self.phase!='idle':return
        self.neutral();self.control=self.choice.get();self.seen.clear()
        self.phase='waiting';self.deadline=time.monotonic()+8;self.last_second=None
        self.button.configure(state='disabled');self.combo.configure(state='disabled')
        self.log('Запланировано ОДНО '+self.control+'. Переключитесь в игру и наведите курсор.')

    def cancel(self):
        self.phase='idle'
        try:self.neutral()
        except Exception as exc:self.log('Не удалось сбросить геймпад: '+str(exc))
        self.status.set('Остановлено')
        if self.pad:self.button.configure(state='normal')
        self.combo.configure(state='readonly')

    def readback(self):
        for slot in range(4):
            state=C.create_string_buffer(16)
            if self.x.XInputGetState(slot,C.byref(state))!=0:continue
            data=state.raw;buttons=int.from_bytes(data[4:6],'little')
            pressed=(data[7]>200 if self.control=='RT' else data[6]>200 if self.control=='LT' else bool(buttons&CONTROLS[self.control]))
            if pressed:self.seen.add(slot)

    def tick(self):
        if self.closed:return
        try:
            now=time.monotonic()
            if self.phase!='idle' and self.u.GetAsyncKeyState(0x1B)&0x8000:
                self.cancel();self.log('Отменено через Esc')
            elif self.phase=='waiting':
                remaining=max(0,int(self.deadline-now+.999))
                self.status.set(f'{self.control}: через {remaining} с')
                if now>=self.deadline:
                    title=C.create_unicode_buffer(1024)
                    self.u.GetWindowTextW(self.u.GetForegroundWindow(),title,len(title))
                    if not re.search(r'aion[\s_-]*2',title.value,re.I):
                        self.log('Не отправлено: активно другое окно '+repr(title.value));self.cancel()
                    else:
                        self.phase='pressed';self.deadline=now+.20
                        press_control(self.pad,self.vg,self.control)
                        self.log('TX: '+self.control+' нажата (не подтверждение игры)')
            elif self.phase=='pressed':
                self.readback()
                if now>=self.deadline:
                    self.neutral();self.phase='idle'
                    self.log(self.control+' отпущена. Windows увидела нажатие в слотах '+str(sorted(self.seen)))
                    self.status.set('Готово. Проверьте действие в игре.')
                    self.button.configure(state='normal');self.combo.configure(state='readonly')
        except Exception as exc:
            self.log('Ошибка: '+str(exc));self.cancel()
        self.root.after(20,self.tick)

    def close(self):
        self.closed=True;self.cancel();self.pad=None;self.root.destroy()


if __name__=='__main__':
    if os.name!='nt':raise SystemExit('Тест предназначен для Windows')
    import tkinter as tk
    root=tk.Tk();App(root);root.mainloop()
