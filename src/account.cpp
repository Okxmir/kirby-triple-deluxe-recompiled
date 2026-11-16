#include "hle/service.h"
#include "memory.h"

#include <cstring>
#include <limits>

namespace hle {
namespace {

class AccountService final : public Service {
public:
    AccountService() : Service("act:u") {}

    void handle(Request &request) override {
        if (request.header() == 0x00010084) { // Initialize an offline session
            request.reply(1, 0);
            return;
        }
        constexpr uint32_t current_account = 0xfe;
        constexpr uint32_t account_id = 0x08;
        constexpr uint32_t account_id_size = 17;
        if (request.header() == 0x000600c2 && request.arg(0) == current_account &&
            request.arg(1) == account_id_size && request.arg(2) == account_id) {
            const uint32_t descriptor = request.arg(3);
            const uint32_t address = request.arg(4);
            constexpr uint32_t invalid_buffer = 0xd9001830;
            if (descriptor != ((account_id_size << 4) | 0xc) ||
                address > std::numeric_limits<uint32_t>::max() - (account_id_size - 1) ||
                !mem::is_committed(address) || !mem::is_committed(address + account_id_size - 1)) {
                request.reply(1, 0, invalid_buffer);
                return;
            }
            // The local profile has no Nintendo Network account ID.
            std::memset(mem::ptr(address), 0, account_id_size);
            auto response = request.reply(1, 2);
            response.push(descriptor);
            response.push(address);
            return;
        }
        unimplemented(*this, request);
    }
};

} // namespace

void register_kirby_account() {
    register_service({"act:u"}, std::make_shared<AccountService>());
}

} // namespace hle
