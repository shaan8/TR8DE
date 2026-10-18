// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {Script, console2} from "forge-std/Script.sol";
import {TiwalaAgentWallet} from "../src/TiwalaAgentWallet.sol";

/// @notice Phase 2: close the two seeded deals after their deadline, so Lumen's record shows 2 late deliveries.
contract Finish is Script {
    function run() external {
        uint256 pk = vm.envUint("PRIVATE_KEY");
        string memory json = vm.readFile(string.concat("deployments/", vm.toString(block.chainid), ".json"));
        address[] memory nb = vm.parseJsonAddressArray(json, ".networkWallets");
        uint256[] memory ids = vm.parseJsonUintArray(json, ".lateDealIds");
        uint256 lateDeadline = vm.parseJsonUint(json, ".lateDeadline");
        require(block.timestamp > lateDeadline, "wait until lateDeadline has passed");

        // late deals live in network buyers 1 and 2
        for (uint256 j = 0; j < 2; j++) {
            uint256 i = j + 1;
            uint256 bpk = uint256(keccak256(abi.encode(pk, "tiwala.network-buyer", i)));
            TiwalaAgentWallet w = TiwalaAgentWallet(nb[i]);
            (,,,,, TiwalaAgentWallet.Status st,,) = w.deals(ids[j]);
            if (st != TiwalaAgentWallet.Status.DownPaid) {
                console2.log("skip deal (already closed)", ids[j]);
                continue;
            }
            vm.startBroadcast(bpk);
            w.confirmDelivery(ids[j]);
            w.releaseBalance(ids[j]);
            vm.stopBroadcast();
        }
        console2.log("late deals closed");
    }
}
