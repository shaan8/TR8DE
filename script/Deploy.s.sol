// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {Script, console2} from "forge-std/Script.sol";
import {SettlementToken} from "../src/SettlementToken.sol";
import {TiwalaFactory} from "../src/TiwalaFactory.sol";
import {TiwalaAgentWallet} from "../src/TiwalaAgentWallet.sol";

/// @notice Phase 1 of the Sepolia (or anvil) deployment.
///   1. Deploy tPHP and the factory (deployer = platform = token issuer).
///   2. Create the demo buyer wallet (OWNER key, AGENT key) and 4 network buyer wallets.
///   3. Seed on-time history across suppliers, and open 2 deals that will close late.
///   4. Write deployments/<chainId>.json for the agent runtime.
/// Run Finish.s.sol once LATE_WINDOW seconds have passed to close the 2 late deals.
///
/// Env: PRIVATE_KEY, OWNER_PRIVATE_KEY, AGENT_PRIVATE_KEY, ACCOUNT_SALT (bytes32),
///      optional BUYER_FUND_WEI (default 0.01 ether), PAYEE_DELAY (default 1 day), LATE_WINDOW (default 120 s),
///      DEMO_GRACE (default 600 s).
contract Deploy is Script {
    uint256 constant PHP = 100; // 2 decimals

    SettlementToken token;
    TiwalaFactory factory;
    uint256 pk;
    bytes32 salt;
    uint256 fund;
    uint256[4] bpk;
    address[4] bw;

    // Suppliers have no on-chain role, so plain deterministic addresses are enough.
    address public lumen = _sup("lumen-textiles");
    address public bayani = _sup("bayani-weaves");
    address public mabuhay = _sup("mabuhay-packaging");
    address public print = _sup("pilipinas-print");

    function run() external {
        pk = vm.envUint("PRIVATE_KEY");
        uint256 ownerPk = vm.envUint("OWNER_PRIVATE_KEY");
        address owner = vm.addr(ownerPk);
        address agent = vm.addr(vm.envUint("AGENT_PRIVATE_KEY"));
        salt = vm.envBytes32("ACCOUNT_SALT");
        fund = vm.envOr("BUYER_FUND_WEI", uint256(0.01 ether));
        uint64 lateWindow = uint64(vm.envOr("LATE_WINDOW", uint256(120)));
        uint64 demoGrace = uint64(vm.envOr("DEMO_GRACE", uint256(600)));

        // ---- platform setup
        vm.startBroadcast(pk);
        token = new SettlementToken("Tokenized PHP Deposit", "tPHP");
        factory = new TiwalaFactory();

        address demo = factory.createWallet(
            address(token), owner, agent, 200_000 * PHP, 150_000 * PHP, 150_000 * PHP, 0, _hashes(salt, "demo-owner")
        );
        token.mint(demo, 200_000 * PHP);
        _topUp(owner, fund * 2);
        _topUp(agent, fund * 2);

        for (uint256 i = 0; i < 4; i++) {
            _makeBuyer(i);
        }
        vm.stopBroadcast();

        // ---- network history (each buyer signs with its own owner key)
        // Lumen: 7 on time + 2 late across 4 buyers. Background suppliers give each buyer history (beta).
        uint256[2] memory lateIds;
        uint64 lateDeadline = uint64(block.timestamp) + lateWindow;

        _asOwner(bpk[0], bw[0], lumen, mabuhay, print);
        _onTime(bw[0], lumen, 100_000, 3000, "N1-L1");
        _onTime(bw[0], lumen, 95_000, 3000, "N1-L2");
        _onTime(bw[0], lumen, 110_000, 3000, "N1-L3");
        _onTime(bw[0], mabuhay, 40_000, 2000, "N1-M1");
        _onTime(bw[0], print, 30_000, 2000, "N1-P1");
        vm.stopBroadcast();

        _asOwner(bpk[1], bw[1], lumen, mabuhay, print);
        _onTime(bw[1], lumen, 80_000, 2500, "N2-L1");
        _onTime(bw[1], lumen, 85_000, 2500, "N2-L2");
        lateIds[0] = _openLate(bw[1], lumen, 90_000, 2500, lateDeadline, "N2-L3-late");
        _onTime(bw[1], mabuhay, 35_000, 2000, "N2-M1");
        _onTime(bw[1], print, 28_000, 2000, "N2-P1");
        vm.stopBroadcast();

        _asOwner(bpk[2], bw[2], lumen, mabuhay, print);
        _onTime(bw[2], lumen, 120_000, 2000, "N3-L1");
        lateIds[1] = _openLate(bw[2], lumen, 115_000, 2000, lateDeadline, "N3-L2-late");
        _onTime(bw[2], mabuhay, 45_000, 2000, "N3-M1");
        _onTime(bw[2], print, 32_000, 2000, "N3-P1");
        vm.stopBroadcast();

        _asOwner(bpk[3], bw[3], lumen, mabuhay, print);
        TiwalaAgentWallet(bw[3]).addSupplier(bayani);
        _onTime(bw[3], lumen, 70_000, 2000, "N4-L1");
        _onTime(bw[3], mabuhay, 38_000, 2000, "N4-M1");
        _onTime(bw[3], print, 26_000, 2000, "N4-P1");
        _onTime(bw[3], bayani, 60_000, 2000, "N4-B1");
        vm.stopBroadcast();

        // ---- demo buyer: knows Bayani (1 on-time deal), Lumen is new to it (stranger cap applies)
        vm.startBroadcast(ownerPk);
        TiwalaAgentWallet dw = TiwalaAgentWallet(demo);
        dw.addSupplier(lumen);
        dw.addSupplier(bayani);
        _onTime(demo, bayani, 50_000, 2000, "PO-098");
        // From now on, newly added payees wait PAYEE_DELAY seconds before they can be paid (default 1 day, the
        // production setting; the run scripts use 10 minutes so judges can see the rule without losing a day).
        // Short grace so the overdue beat fits the video.
        dw.setLimits(200_000 * PHP, 150_000 * PHP, 150_000 * PHP, uint64(vm.envOr("PAYEE_DELAY", uint256(1 days))));
        dw.setEscrowPolicy(5000, demoGrace);
        vm.stopBroadcast();

        _write(demo, owner, agent, lateIds, lateDeadline);
    }

    // ------------------------------------------------------------- helpers

    function _makeBuyer(uint256 i) internal {
        bpk[i] = uint256(keccak256(abi.encode(pk, "tiwala.network-buyer", i)));
        address bo = vm.addr(bpk[i]);
        address bagent = address(uint160(uint256(keccak256(abi.encode("tiwala.network-agent", i)))));
        bw[i] = factory.createWallet(
            address(token),
            bo,
            bagent,
            1_000_000 * PHP,
            1_000_000 * PHP,
            1_000_000 * PHP,
            0,
            _hashes(salt, string.concat("network-buyer-", vm.toString(i)))
        );
        token.mint(bw[i], 1_000_000 * PHP);
        _topUp(bo, fund);
    }

    function _asOwner(uint256 opk, address w, address a, address b, address c) internal {
        vm.startBroadcast(opk);
        TiwalaAgentWallet(w).addSupplier(a);
        TiwalaAgentWallet(w).addSupplier(b);
        TiwalaAgentWallet(w).addSupplier(c);
    }

    function _onTime(address w, address sup, uint256 php, uint16 bps, string memory ref) internal {
        TiwalaAgentWallet wal = TiwalaAgentWallet(w);
        uint256 id = wal.createDeal(sup, php * PHP, bps, uint64(block.timestamp + 30 days), ref);
        wal.releaseDownPayment(id);
        wal.confirmDelivery(id);
        wal.releaseBalance(id);
    }

    function _openLate(address w, address sup, uint256 php, uint16 bps, uint64 deadline, string memory ref)
        internal
        returns (uint256 id)
    {
        TiwalaAgentWallet wal = TiwalaAgentWallet(w);
        id = wal.createDeal(sup, php * PHP, bps, deadline, ref);
        wal.releaseDownPayment(id);
    }

    function _topUp(address to, uint256 amount) internal {
        if (to.balance < amount) payable(to).transfer(amount - to.balance);
    }

    function _hashes(bytes32 salt, string memory who) internal pure returns (bytes32[] memory h) {
        h = new bytes32[](2);
        h[0] = keccak256(abi.encodePacked(salt, "gcash:", who));
        h[1] = keccak256(abi.encodePacked(salt, "bank:", who));
    }

    function _sup(string memory label) internal pure returns (address) {
        return address(uint160(uint256(keccak256(abi.encodePacked("tiwala.supplier.", label)))));
    }

    function _write(
        address demo,
        address owner,
        address agent,
        uint256[2] memory lateIds,
        uint64 lateDeadline
    ) internal {
        string memory k = "deploy";
        vm.serializeUint(k, "chainId", block.chainid);
        vm.serializeUint(k, "startBlock", block.number);
        vm.serializeAddress(k, "token", address(token));
        vm.serializeAddress(k, "factory", address(factory));
        vm.serializeAddress(k, "demoWallet", demo);
        vm.serializeAddress(k, "owner", owner);
        vm.serializeAddress(k, "agent", agent);
        address[] memory nb = new address[](4);
        for (uint256 i = 0; i < 4; i++) nb[i] = bw[i];
        vm.serializeAddress(k, "networkWallets", nb);
        vm.serializeUint(k, "lateDeadline", lateDeadline);
        uint256[] memory li = new uint256[](2);
        li[0] = lateIds[0];
        li[1] = lateIds[1];
        vm.serializeUint(k, "lateDealIds", li);

        string memory s = "suppliers";
        vm.serializeAddress(s, "Lumen Textiles", lumen);
        vm.serializeAddress(s, "Bayani Weaves", bayani);
        vm.serializeAddress(s, "Mabuhay Packaging", mabuhay);
        string memory sj = vm.serializeAddress(s, "Pilipinas Print", print);
        string memory json = vm.serializeString(k, "suppliers", sj);

        string memory path = string.concat("deployments/", vm.toString(block.chainid), ".json");
        vm.writeJson(json, path);
        console2.log("wrote", path);
    }
}
