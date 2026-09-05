#include <stdarg.h>
#include "iup.h"

Ihandle *IupHbox(Ihandle *child, ...) {
    va_list ap;
    Ihandle *next;
    (void)child;
    va_start(ap, child);
    do {
        next = va_arg(ap, Ihandle *);
    } while (next != NULL);
    va_end(ap);
    return NULL;
}

Ihandle *IupToggle(const char *title, const char *action) {
    (void)title;
    (void)action;
    return NULL;
}

Ihandle *IupLabel(const char *title) {
    (void)title;
    return NULL;
}

Ihandle *IupText(const char *action) {
    (void)action;
    return NULL;
}

Ihandle *IupButton(const char *title, const char *action) {
    (void)title;
    (void)action;
    return NULL;
}

Ihandle *IupImageRGBA(int width, int height, const unsigned char *pixels) {
    (void)width;
    (void)height;
    (void)pixels;
    return NULL;
}

void IupSetAttribute(Ihandle *ih, const char *name, const char *value) {
    (void)ih;
    (void)name;
    (void)value;
}

void IupStoreAttribute(Ihandle *ih, const char *name, const char *value) {
    (void)ih;
    (void)name;
    (void)value;
}

char *IupGetAttribute(Ihandle *ih, const char *name) {
    (void)ih;
    (void)name;
    return NULL;
}

int IupGetInt(Ihandle *ih, const char *name) {
    (void)ih;
    (void)name;
    return 0;
}

float IupGetFloat(Ihandle *ih, const char *name) {
    (void)ih;
    (void)name;
    return 0.0f;
}

Icallback IupSetCallback(Ihandle *ih, const char *name, Icallback cb) {
    (void)ih;
    (void)name;
    (void)cb;
    return NULL;
}

Icallback IupGetCallback(Ihandle *ih, const char *name) {
    (void)ih;
    (void)name;
    return NULL;
}

char *IupGetGlobal(const char *name) {
    (void)name;
    return NULL;
}

void IupStoreGlobal(const char *name, const char *value) {
    (void)name;
    (void)value;
}

void IupSetHandle(const char *name, Ihandle *ih) {
    (void)name;
    (void)ih;
}

void showStatus(const char *line) {
    (void)line;
}
