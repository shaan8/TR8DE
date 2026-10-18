// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {Test} from "forge-std/Test.sol";
import {TiwalaAgentWallet} from "../../src/TiwalaAgentWallet.sol";
import {SettlementToken} from "../../src/SettlementToken.sol";

/// @notice Drives the wallet with random sequences of owner and agent actions,
///         tracking an independent model of what escrow should hold.
contract Handler is Test {
    TiwalaAgentWallet public w;
    SettlementToken public token;
    address public owner;
    address public agent;
    address[3] public sups;

    uint256[] public ids;
    /// @dev ghost: amount paid to suppliers before the owner attested, per deal
    mapping(uint256 => uint256) public preAttestPaid;
    uint256 public ghostPaidOut;
    mapping(uint256 => bool) public byAgent;

    constructor(TiwalaAgentWallet _w, SettlementToken _t, address _owner, address _agent, address[3] memory _sups) {
        w = _w;
        token = _t;
        owner = _owner;
        agent = _agent;
        sups = _sups;
    }

    function _id(uint256 seed) internal view returns (uint256) {
        return ids.length == 0 ? 0 : ids[seed % ids.length];
    }

    function _actor(bool asOwner) internal view returns (address) {
        return asOwner ? owner : agent;
    }

    function create(uint256 supSeed, uint256 total, uint16 bps, uint32 dl, bool asOwner) external {
        total = bound(total, 1, w.perDealCap());
        bps = uint16(bound(bps, 0, asOwner ? 10_000 : w.maxDownBps()));
        dl = uint32(bound(dl, 1 hours, 30 days));
        if (w.freeBalance() < total) return;
        vm.prank(_actor(asOwner));
        uint256 id = w.createDeal(sups[supSeed % 3], total, bps, uint64(block.timestamp + dl), "PO");
        ids.push(id);
        byAgent[id] = !asOwner;
    }

    function approve(uint256 seed) external {
        uint256 id = _id(seed);
        (,,,,, TiwalaAgentWallet.Status s,,) = w.deals(id);
        if (s != TiwalaAgentWallet.Status.Locked) return;
        vm.prank(owner);
        w.approveDeal(id);
    }

    function releaseDown(uint256 seed, bool asOwner) external {
        uint256 id = _id(seed);
        (,,,,, TiwalaAgentWallet.Status s, bool ok,) = w.deals(id);
        if (s != TiwalaAgentWallet.Status.Locked || !ok) return;
        uint256 amt = w.downAmount(id);
        if (!asOwner && w.spentToday() + amt > w.dailyCap() && block.timestamp / 1 days == w.currentDay()) return;
        vm.prank(_actor(asOwner));
        w.releaseDownPayment(id);
        preAttestPaid[id] += amt;
        ghostPaidOut += amt;
    }

    function confirm(uint256 seed) external {
        uint256 id = _id(seed);
        (,,,,, TiwalaAgentWallet.Status s,,) = w.deals(id);
        if (s != TiwalaAgentWallet.Status.DownPaid) return;
        vm.prank(owner);
        w.confirmDelivery(id);
    }

    function releaseBal(uint256 seed, bool asOwner) external {
        uint256 id = _id(seed);
        (, uint256 total,,,, TiwalaAgentWallet.Status s,,) = w.deals(id);
        if (s != TiwalaAgentWallet.Status.Delivered) return;
        uint256 amt = total - w.downAmount(id);
        if (!asOwner && w.spentToday() + amt > w.dailyCap() && block.timestamp / 1 days == w.currentDay()) return;
        vm.prank(_actor(asOwner));
        w.releaseBalance(id);
        ghostPaidOut += amt;
    }

    function cancel(uint256 seed, bool asOwner) external {
        uint256 id = _id(seed);
        (,,, uint64 dl,, TiwalaAgentWallet.Status s,,) = w.deals(id);
        bool overdue = block.timestamp > uint256(dl) + w.grace();
        if (s == TiwalaAgentWallet.Status.Locked && (asOwner || overdue)) {
            vm.prank(_actor(asOwner));
            w.cancelDeal(id);
        } else if (s == TiwalaAgentWallet.Status.DownPaid && overdue) {
            vm.prank(_actor(asOwner));
            w.cancelDeal(id);
        }
    }

    function dispute(uint256 seed, bool release) external {
        uint256 id = _id(seed);
        (, uint256 total,,,, TiwalaAgentWallet.Status s,,) = w.deals(id);
        if (s != TiwalaAgentWallet.Status.DownPaid) return;
        vm.startPrank(owner);
        w.raiseDispute(id);
        w.resolveDispute(id, release);
        vm.stopPrank();
        if (release) ghostPaidOut += total - w.downAmount(id);
    }

    function warp(uint32 secs) external {
        vm.warp(block.timestamp + bound(secs, 1, 10 days));
    }

    function idsLength() external view returns (uint256) {
        return ids.length;
    }
}

contract EscrowInvariants is Test {
    TiwalaAgentWallet w;
    SettlementToken token;
    Handler h;
    uint256 constant FUNDED = 10_000_000_00;

    function setUp() public {
        vm.warp(1_760_000_000);
        address owner = makeAddr("owner");
        address agent = makeAddr("agent");
        address[3] memory sups = [makeAddr("s1"), makeAddr("s2"), makeAddr("s3")];
        token = new SettlementToken("Tokenized PHP Deposit", "tPHP");
        w = new TiwalaAgentWallet(address(token), owner, agent, 2_000_000_00, 3_000_000_00, 1_000_000_00, 0);
        token.mint(address(w), FUNDED);
        vm.startPrank(owner);
        for (uint256 i; i < 3; i++) w.addSupplier(sups[i]);
        vm.stopPrank();
        h = new Handler(w, token, owner, agent, sups);
        targetContract(address(h));
    }

    /// I1: `locked` equals the sum of unpaid escrow across open deals.
    function invariant_LockedMatchesOpenDeals() public view {
        uint256 sum;
        uint256 n = h.idsLength();
        for (uint256 i; i < n; i++) {
            uint256 id = h.ids(i);
            (, uint256 total,,,, TiwalaAgentWallet.Status s,,) = w.deals(id);
            if (s == TiwalaAgentWallet.Status.Locked) sum += total;
            else if (
                s == TiwalaAgentWallet.Status.DownPaid || s == TiwalaAgentWallet.Status.Delivered
                    || s == TiwalaAgentWallet.Status.Disputed
            ) sum += total - w.downAmount(id);
        }
        assertEq(w.locked(), sum);
    }

    /// I2: tokens are conserved: wallet balance + everything paid out == funded.
    function invariant_Conservation() public view {
        assertEq(token.balanceOf(address(w)) + h.ghostPaidOut(), FUNDED);
        assertGe(token.balanceOf(address(w)), w.locked());
    }

    /// I3: before attestation, no agent-created deal has paid out more than maxDownBps of its total.
    function invariant_PreAttestationBounded() public view {
        uint256 n = h.idsLength();
        for (uint256 i; i < n; i++) {
            uint256 id = h.ids(i);
            (, uint256 total,,,,,,) = w.deals(id);
            assertLe(h.preAttestPaid(id), w.downAmount(id));
            if (h.byAgent(id)) assertLe(h.preAttestPaid(id), (total * w.maxDownBps()) / 10_000);
        }
    }
}
