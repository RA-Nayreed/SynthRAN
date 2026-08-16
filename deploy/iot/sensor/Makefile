CONTIKI_PROJECT = synthran-sensor
all: $(CONTIKI_PROJECT)

ifndef CONTIKI
$(error CONTIKI must point at the pinned Contiki-NG checkout)
endif

include $(CONTIKI)/Makefile.dir-variables
MODULES += $(CONTIKI_NG_APP_LAYER_DIR)/mqtt

include $(CONTIKI)/Makefile.identify-target
MODULES_REL += arch/platform/$(TARGET)

PLATFORMS_ONLY = cooja

include $(CONTIKI)/Makefile.include
