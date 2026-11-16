#pragma once

#include <SDL3/SDL.h>
#include <cstring>

#include "frontend/settings.h"
#include "log.h"
#include "video/pica.h"

namespace frontend {

class LinuxUpscaling {
public:
    LinuxUpscaling(Settings &settings, bool available) : settings_(settings), available_(available) {}

    float height() const { return available_ && !settings_.fullscreen ? strip_height : 0; }

    bool click(float x, float y) {
        if (y < 0 || y >= height()) return false;
        const SDL_FPoint point{x, y};
        for (int i = 0; i < 3; ++i) {
            const SDL_FRect button = option_rect(i);
            if (!SDL_PointInRectFloat(&point, &button) || settings_.resolution == scales[i]) continue;
            settings_.resolution = scales[i];
            pica::set_resolution_scale(settings_.resolution);
            settings_.save();
            LOG("graphics: resolution set to %dx", settings_.resolution);
            return true;
        }
        return false;
    }

    void draw(SDL_Renderer *renderer, float width) const {
        if (height() == 0) return;
        const SDL_FRect strip{0, 0, width, strip_height};
        SDL_SetRenderDrawColor(renderer, 32, 32, 32, 255);
        SDL_RenderFillRect(renderer, &strip);
        SDL_SetRenderDrawColor(renderer, 242, 242, 242, 255);
        SDL_RenderDebugText(renderer, 6, 6, label());
        for (int i = 0; i < 3; ++i) {
            const SDL_FRect button = option_rect(i);
            if (settings_.resolution == scales[i])
                SDL_SetRenderDrawColor(renderer, 42, 92, 154, 255);
            else
                SDL_SetRenderDrawColor(renderer, 65, 65, 65, 255);
            SDL_RenderFillRect(renderer, &button);
            SDL_SetRenderDrawColor(renderer, 242, 242, 242, 255);
            SDL_RenderDebugText(renderer, button.x + 6, 6, scale_labels[i]);
        }
    }

private:
    static constexpr float strip_height = 20;
    static constexpr int scales[] = {1, 2, 4};
    static constexpr const char *scale_labels[] = {"1x", "2x", "4x"};
    static constexpr const char *menu_labels[] = {
        "Upscaling", "Mise a l'echelle", "Hochskalierung", "Ridimensionamento", "Escalado"
    };

    const char *label() const { return menu_labels[settings_.language - 1]; }

    SDL_FRect option_rect(int i) const {
        const float start = 12 + float(std::strlen(label()) * SDL_DEBUG_TEXT_FONT_CHARACTER_SIZE);
        return {start + float(i) * 32, 2, 28, 16};
    }

    Settings &settings_;
    bool available_;
};

} // namespace frontend
