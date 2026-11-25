LOCAL_PATH := $(call my-dir)
include $(CLEAR_VARS)
LOCAL_MODULE := padchord
LOCAL_SRC_FILES := pad_chord.c
LOCAL_CFLAGS := -std=c11 -D_GNU_SOURCE -Wall -Wextra
include $(BUILD_SHARED_LIBRARY)
