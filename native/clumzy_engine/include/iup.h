/* Minimal IUP stub so the Clumzy packet engine can compile without the IUP GUI. */
#ifndef __IUP_H
#define __IUP_H

#ifdef __cplusplus
extern "C" {
#endif

typedef struct Ihandle_ Ihandle;
typedef int (*Icallback)(Ihandle *);
typedef int (*IstateCallback)(Ihandle *, int);

#define IUP_IGNORE (-1)
#define IUP_DEFAULT 0
#define IUP_CLOSE 1

Ihandle *IupHbox(Ihandle *child, ...);
Ihandle *IupToggle(const char *title, const char *action);
Ihandle *IupLabel(const char *title);
Ihandle *IupText(const char *action);
Ihandle *IupButton(const char *title, const char *action);
Ihandle *IupImageRGBA(int width, int height, const unsigned char *pixels);

void IupSetAttribute(Ihandle *ih, const char *name, const char *value);
void IupStoreAttribute(Ihandle *ih, const char *name, const char *value);
char *IupGetAttribute(Ihandle *ih, const char *name);
int IupGetInt(Ihandle *ih, const char *name);
float IupGetFloat(Ihandle *ih, const char *name);
Icallback IupSetCallback(Ihandle *ih, const char *name, Icallback cb);
Icallback IupGetCallback(Ihandle *ih, const char *name);
char *IupGetGlobal(const char *name);
void IupStoreGlobal(const char *name, const char *value);
void IupSetHandle(const char *name, Ihandle *ih);

void showStatus(const char *line);

#ifdef __cplusplus
}
#endif

#endif
