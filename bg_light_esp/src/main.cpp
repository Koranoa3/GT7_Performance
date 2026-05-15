#include <Arduino.h>

#include "background_light_controller.h"

namespace
{
bg_light::BackgroundLightController controller;
}

void setup()
{
  controller.setup();
}

void loop()
{
  controller.loop();
  delay(1);
}
