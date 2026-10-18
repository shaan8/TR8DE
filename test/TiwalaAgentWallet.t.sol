// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "forge-std/Test.sol";
import "../src/TiwalaAgentWallet.sol";
import "../src/TiwalaFactory.sol";
import "../src/SettlementToken.sol";

contract TiwalaAgentWalletTest is Test {
    SettlementToken token;
    TiwalaFactory factory;
    TiwalaAgentWallet w;

    address platform = address(this);
    address owner = makeAddr("owner");
    address agent = makeAddr("agent");
    address supplier = makeAddr("supplier");
    address stranger = makeAddr("stranger");

    // amounts in centavos (2 decimals): 100 = PHP 1.00
    uint256 constant PHP = 100;
    uint256 constant PER_DEAL_CAP = 500_000 * PHP;
    uint256 constant DAILY_CAP = 300_000 * PHP;
    uint256 constant APPROVAL = 200_000 * PHP;
    uint64 constant DELAY = 1 days;

    function setUp() public {
        vm.warp(1_760_000_000);
        token = new SettlementToken("Tokenized PHP Deposit", "tPHP");
        factory = new TiwalaFactory();
        w = TiwalaAgentWallet(
            factory.createWallet(address(token), owner, agent, PER_DEAL_CAP, DAILY_CAP, APPROVAL, DELAY, _h("gcash:owner"))
        );
        token.mint(address(w), 1_000_000 * PHP);
        vm.prank(owner);
        w.addSupplier(supplier);
        vm.warp(block.timestamp + DELAY);
    }

    // ---------------- helpers ----------------

    function _h(string memory s) internal pure returns (bytes32[] memory a) {
        a = new bytes32[](1);
        a[0] = keccak256(bytes(s));
    }

    function _deal(uint256 total, uint16 bps) internal returns (uint256 id) {
        vm.prank(agent);
        id = w.createDeal(supplier, total, bps, uint64(block.timestamp + 7 days), "PO-001");
    }

    function _status(uint256 id) internal view returns (TiwalaAgentWallet.Status s) {
        (,,,,, s,,) = w.deals(id);
    }

    // ---------------- happy path ----------------

    function test_FullLifecycle_OnTime() public {
        uint256 id = _deal(100_000 * PHP, 3000);
        assertEq(w.locked(), 100_000 * PHP);
        assertEq(w.freeBalance(), 900_000 * PHP);

        vm.prank(agent);
        w.releaseDownPayment(id);
        assertEq(token.balanceOf(supplier), 30_000 * PHP);

        vm.prank(owner);
        w.confirmDelivery(id);

        vm.prank(agent);
        w.releaseBalance(id);
        assertEq(token.balanceOf(supplier), 100_000 * PHP);
        assertEq(w.locked(), 0);
        assertEq(uint8(_status(id)), uint8(TiwalaAgentWallet.Status.Completed));
        (uint32 c, uint32 l) = w.supplierRecord(supplier);
        assertEq(c, 1);
        assertEq(l, 0);
    }

    // ---------------- critical fix: DP cap ----------------

    function test_AgentCannotBypassAttestationWithFullDownPayment() public {
        vm.prank(agent);
        vm.expectRevert(TiwalaAgentWallet.DownPaymentAboveCap.selector);
        w.createDeal(supplier, 100_000 * PHP, 10000, uint64(block.timestamp + 7 days), "PO-X");
    }

    function test_AgentCanUseExactlyMaxDownBps() public {
        uint256 id = _deal(100_000 * PHP, 5000);
        assertEq(w.downAmount(id), 50_000 * PHP);
    }

    function test_OwnerNotBoundByMaxDownBps() public {
        vm.prank(owner);
        w.createDeal(supplier, 100_000 * PHP, 10000, uint64(block.timestamp + 7 days), "PO-prepaid");
    }

    // ---------------- permissions ----------------

    function test_AgentCannotConfirmDelivery() public {
        uint256 id = _deal(100_000 * PHP, 3000);
        vm.prank(agent);
        w.releaseDownPayment(id);
        vm.prank(agent);
        vm.expectRevert(TiwalaAgentWallet.NotOwner.selector);
        w.confirmDelivery(id);
    }

    function test_AgentCannotReleaseBalanceWithoutAttestation() public {
        uint256 id = _deal(100_000 * PHP, 3000);
        vm.prank(agent);
        w.releaseDownPayment(id);
        vm.prank(agent);
        vm.expectRevert(abi.encodeWithSelector(TiwalaAgentWallet.WrongStatus.selector, TiwalaAgentWallet.Status.DownPaid));
        w.releaseBalance(id);
    }

    function test_AgentCannotAddSupplierWithdrawOrDispute() public {
        vm.startPrank(agent);
        vm.expectRevert(TiwalaAgentWallet.NotOwner.selector);
        w.addSupplier(stranger);
        vm.expectRevert(TiwalaAgentWallet.NotOwner.selector);
        w.withdraw(agent, 1);
        vm.expectRevert(TiwalaAgentWallet.NotOwner.selector);
        w.raiseDispute(1);
        vm.expectRevert(TiwalaAgentWallet.NotOwner.selector);
        w.setEscrowPolicy(10000, 0);
        vm.stopPrank();
    }

    function test_StrangerCannotOperate() public {
        vm.prank(stranger);
        vm.expectRevert(TiwalaAgentWallet.NotOperator.selector);
        w.createDeal(supplier, 1, 0, uint64(block.timestamp + 1 days), "x");
    }

    function test_AgentCannotBeOwner() public {
        vm.expectRevert(TiwalaAgentWallet.AgentIsOwner.selector);
        new TiwalaAgentWallet(address(token), owner, owner, 1, 1, 1, 0);
        vm.prank(owner);
        vm.expectRevert(TiwalaAgentWallet.AgentIsOwner.selector);
        w.setAgent(owner);
    }

    function test_NewSupplierNotPayableBeforeDelay() public {
        vm.prank(owner);
        w.addSupplier(stranger);
        vm.prank(agent);
        vm.expectRevert(TiwalaAgentWallet.SupplierNotActive.selector);
        w.createDeal(stranger, 1_000 * PHP, 3000, uint64(block.timestamp + 7 days), "PO-new");
    }

    // ---------------- caps ----------------

    function test_PerDealCap() public {
        vm.prank(agent);
        vm.expectRevert(TiwalaAgentWallet.AmountOutOfRange.selector);
        w.createDeal(supplier, PER_DEAL_CAP + 1, 3000, uint64(block.timestamp + 7 days), "PO-big");
    }

    function test_AgentDailyCap() public {
        // two deals of 150k at 50% DP -> 75k + 75k DP, then balances 75k + 75k = 300k total
        uint256 a = _deal(150_000 * PHP, 5000);
        uint256 b = _deal(150_000 * PHP, 5000);
        uint256 c = _deal(150_000 * PHP, 5000);
        vm.startPrank(agent);
        w.releaseDownPayment(a); // 75k
        w.releaseDownPayment(b); // 150k
        w.releaseDownPayment(c); // 225k
        vm.stopPrank();
        vm.startPrank(owner);
        w.confirmDelivery(a);
        w.confirmDelivery(b);
        vm.stopPrank();
        vm.prank(agent);
        w.releaseBalance(a); // 300k, exactly at cap
        vm.prank(agent);
        vm.expectRevert(TiwalaAgentWallet.DailyCapExceeded.selector);
        w.releaseBalance(b);
        vm.warp(block.timestamp + 1 days);
        vm.prank(agent);
        w.releaseBalance(b); // new day
    }

    function test_ApprovalThreshold() public {
        uint256 id = _deal(APPROVAL + 1, 3000);
        vm.prank(agent);
        vm.expectRevert(TiwalaAgentWallet.ApprovalRequired.selector);
        w.releaseDownPayment(id);
        vm.prank(owner);
        w.approveDeal(id);
        vm.prank(agent);
        w.releaseDownPayment(id);
    }

    function test_InsufficientFreeBalance() public {
        _deal(500_000 * PHP, 3000);
        _deal(500_000 * PHP, 3000);
        vm.prank(agent);
        vm.expectRevert(TiwalaAgentWallet.InsufficientFreeBalance.selector);
        w.createDeal(supplier, 1, 0, uint64(block.timestamp + 7 days), "PO-over");
    }

    function test_PauseBlocksReleases() public {
        uint256 id = _deal(100_000 * PHP, 3000);
        vm.prank(owner);
        w.setPaused(true);
        vm.prank(agent);
        vm.expectRevert(TiwalaAgentWallet.IsPaused.selector);
        w.releaseDownPayment(id);
    }

    // ---------------- deadline + grace ----------------

    function test_AgentCannotCancelBeforeGrace() public {
        uint256 id = _deal(100_000 * PHP, 3000);
        vm.prank(agent);
        w.releaseDownPayment(id);
        vm.warp(block.timestamp + 7 days + 1); // past deadline, inside grace
        vm.prank(agent);
        vm.expectRevert(TiwalaAgentWallet.NotOverdue.selector);
        w.cancelDeal(id);
    }

    function test_AgentCancelsAfterGrace_RefundsBalance_MarksLate() public {
        uint256 id = _deal(100_000 * PHP, 3000);
        vm.prank(agent);
        w.releaseDownPayment(id);
        vm.warp(block.timestamp + 9 days + 1);
        vm.prank(agent);
        w.cancelDeal(id);
        assertEq(uint8(_status(id)), uint8(TiwalaAgentWallet.Status.Refunded));
        assertEq(w.locked(), 0);
        assertEq(w.freeBalance(), 970_000 * PHP);
        (, uint32 l) = w.supplierRecord(supplier);
        assertEq(l, 1);
    }

    function test_OwnerCanCancelLockedAnyTime() public {
        uint256 id = _deal(100_000 * PHP, 3000);
        vm.prank(owner);
        w.cancelDeal(id);
        assertEq(w.locked(), 0);
    }

    function test_OwnerConfirmsInsideGrace_StillLate_ButNotCancellable() public {
        uint256 id = _deal(100_000 * PHP, 3000);
        vm.prank(agent);
        w.releaseDownPayment(id);
        vm.warp(block.timestamp + 8 days);
        vm.prank(owner);
        w.confirmDelivery(id);
        vm.prank(agent);
        vm.expectRevert(abi.encodeWithSelector(TiwalaAgentWallet.WrongStatus.selector, TiwalaAgentWallet.Status.Delivered));
        w.cancelDeal(id);
        vm.prank(agent);
        w.releaseBalance(id);
        (uint32 c, uint32 l) = w.supplierRecord(supplier);
        assertEq(c, 0);
        assertEq(l, 1);
    }

    function test_OnTimeJudgedAtConfirmation_NotRelease() public {
        uint256 id = _deal(100_000 * PHP, 3000);
        vm.prank(agent);
        w.releaseDownPayment(id);
        vm.prank(owner);
        w.confirmDelivery(id); // on time
        vm.warp(block.timestamp + 30 days); // release much later
        vm.prank(agent);
        w.releaseBalance(id);
        (uint32 c, uint32 l) = w.supplierRecord(supplier);
        assertEq(c, 1);
        assertEq(l, 0);
    }

    function test_ExtendDeadline() public {
        uint256 id = _deal(100_000 * PHP, 3000);
        (,,, uint64 dl,,,,) = w.deals(id);
        vm.prank(owner);
        vm.expectRevert(TiwalaAgentWallet.MustExtend.selector);
        w.extendDeadline(id, dl - 1);
        vm.prank(agent);
        vm.expectRevert(TiwalaAgentWallet.NotOwner.selector);
        w.extendDeadline(id, dl + 1 days);
        vm.prank(owner);
        w.extendDeadline(id, dl + 5 days);
        vm.prank(agent);
        w.releaseDownPayment(id);
        vm.warp(dl + 3 days); // old deadline + grace passed, new one has not
        vm.prank(agent);
        vm.expectRevert(TiwalaAgentWallet.NotOverdue.selector);
        w.cancelDeal(id);
    }

    // ---------------- disputes ----------------

    function test_DisputeFreezesAutoCancel() public {
        uint256 id = _deal(100_000 * PHP, 3000);
        vm.prank(agent);
        w.releaseDownPayment(id);
        vm.prank(owner);
        w.raiseDispute(id);
        vm.warp(block.timestamp + 60 days);
        vm.prank(agent);
        vm.expectRevert(abi.encodeWithSelector(TiwalaAgentWallet.WrongStatus.selector, TiwalaAgentWallet.Status.Disputed));
        w.cancelDeal(id);
        vm.prank(agent);
        vm.expectRevert(abi.encodeWithSelector(TiwalaAgentWallet.WrongStatus.selector, TiwalaAgentWallet.Status.Disputed));
        w.releaseBalance(id);
    }

    function test_DisputeReleased_NotCountedLate() public {
        uint256 id = _deal(100_000 * PHP, 3000);
        vm.prank(agent);
        w.releaseDownPayment(id);
        vm.startPrank(owner);
        w.raiseDispute(id);
        w.resolveDispute(id, true);
        vm.stopPrank();
        assertEq(token.balanceOf(supplier), 100_000 * PHP);
        (uint32 c, uint32 l) = w.supplierRecord(supplier);
        assertEq(c, 0);
        assertEq(l, 0);
    }

    function test_DisputeRefunded_CountedLate() public {
        uint256 id = _deal(100_000 * PHP, 3000);
        vm.prank(agent);
        w.releaseDownPayment(id);
        vm.startPrank(owner);
        w.raiseDispute(id);
        w.resolveDispute(id, false);
        vm.stopPrank();
        assertEq(token.balanceOf(supplier), 30_000 * PHP);
        assertEq(w.locked(), 0);
        (, uint32 l) = w.supplierRecord(supplier);
        assertEq(l, 1);
    }

    // ---------------- issuer clawback ----------------

    function test_IssuerBurnDoesNotBrickWallet() public {
        _deal(400_000 * PHP, 3000);
        _deal(200_000 * PHP, 3000);
        token.burn(address(w), 500_000 * PHP); // 500k left, 600k locked
        assertTrue(w.isUnderfunded());
        assertEq(w.freeBalance(), 0); // no revert
        vm.prank(agent);
        vm.expectRevert(TiwalaAgentWallet.InsufficientFreeBalance.selector);
        w.createDeal(supplier, 1, 0, uint64(block.timestamp + 7 days), "PO-y");
    }

    // ---------------- factory ----------------

    function test_FactoryRejectsReusedAccount() public {
        vm.expectRevert(
            abi.encodeWithSelector(TiwalaFactory.AccountAlreadyLinked.selector, keccak256("gcash:owner"), address(w))
        );
        factory.createWallet(address(token), stranger, agent, 1, 1, 1, 0, _h("gcash:owner"));
    }

    function test_FactoryOnlyPlatform() public {
        vm.prank(stranger);
        vm.expectRevert(TiwalaFactory.NotPlatform.selector);
        factory.createWallet(address(token), stranger, agent, 1, 1, 1, 0, _h("gcash:stranger"));
    }

    function test_FactoryRegistersWallet() public {
        address w2 = factory.createWallet(address(token), stranger, agent, 1, 1, 1, 0, _h("maya:stranger"));
        assertTrue(factory.isWallet(w2));
        assertEq(factory.walletOfAccount(keccak256("maya:stranger")), w2);
        assertEq(factory.walletCount(), 2);
        assertEq(TiwalaAgentWallet(w2).owner(), stranger);
    }


    // ---------------- admin and input validation ----------------

    function test_OwnerAdmin() public {
        vm.startPrank(owner);
        w.setLimits(1, 2, 3, 4);
        assertEq(w.perDealCap(), 1);
        w.setEscrowPolicy(4000, 1 days);
        assertEq(w.maxDownBps(), 4000);
        vm.expectRevert(TiwalaAgentWallet.BadBps.selector);
        w.setEscrowPolicy(10001, 0);
        w.setAgent(stranger);
        assertEq(w.agent(), stranger);
        vm.expectRevert(TiwalaAgentWallet.ZeroAddress.selector);
        w.setAgent(address(0));
        vm.stopPrank();
    }

    function test_AddSupplierRejectsBadPayees() public {
        vm.startPrank(owner);
        vm.expectRevert(TiwalaAgentWallet.BadSupplier.selector);
        w.addSupplier(address(0));
        vm.expectRevert(TiwalaAgentWallet.BadSupplier.selector);
        w.addSupplier(agent);
        vm.expectRevert(TiwalaAgentWallet.BadSupplier.selector);
        w.addSupplier(owner);
        vm.expectRevert(TiwalaAgentWallet.BadSupplier.selector);
        w.addSupplier(address(w));
        vm.stopPrank();
    }

    function test_RemovedSupplierCannotReceiveDownPayment() public {
        uint256 id = _deal(100_000 * PHP, 3000);
        vm.prank(owner);
        w.removeSupplier(supplier);
        vm.prank(agent);
        vm.expectRevert(TiwalaAgentWallet.SupplierRemoved.selector);
        w.releaseDownPayment(id);
    }

    function test_WithdrawOnlyFreeBalance() public {
        _deal(400_000 * PHP, 3000);
        vm.startPrank(owner);
        vm.expectRevert(TiwalaAgentWallet.InsufficientFreeBalance.selector);
        w.withdraw(owner, 600_001 * PHP);
        vm.expectRevert(TiwalaAgentWallet.ZeroAddress.selector);
        w.withdraw(address(0), 1);
        w.withdraw(owner, 600_000 * PHP);
        vm.stopPrank();
        assertEq(token.balanceOf(owner), 600_000 * PHP);
        assertEq(w.freeBalance(), 0);
    }

    function test_CreateDealValidation() public {
        vm.startPrank(agent);
        vm.expectRevert(TiwalaAgentWallet.DeadlineInPast.selector);
        w.createDeal(supplier, 1, 0, uint64(block.timestamp), "x");
        vm.expectRevert(TiwalaAgentWallet.AmountOutOfRange.selector);
        w.createDeal(supplier, 0, 0, uint64(block.timestamp + 1), "x");
        vm.stopPrank();
        vm.prank(owner);
        vm.expectRevert(TiwalaAgentWallet.BadBps.selector);
        w.createDeal(supplier, 1, 10001, uint64(block.timestamp + 1), "x");
    }

    function test_ConstructorRejectsZeroAddresses() public {
        vm.expectRevert(TiwalaAgentWallet.ZeroAddress.selector);
        new TiwalaAgentWallet(address(0), owner, agent, 1, 1, 1, 0);
    }

    function test_AgentCannotCancelLockedBeforeGrace() public {
        uint256 id = _deal(100_000 * PHP, 3000);
        vm.prank(agent);
        vm.expectRevert(TiwalaAgentWallet.NotOverdue.selector);
        w.cancelDeal(id);
        vm.warp(block.timestamp + 9 days + 1);
        vm.prank(agent);
        w.cancelDeal(id);
        (, uint32 l) = w.supplierRecord(supplier);
        assertEq(l, 0); // no down payment was paid, so no strike
    }

    function test_WrongStatusTransitions() public {
        uint256 id = _deal(100_000 * PHP, 3000);
        vm.startPrank(owner);
        vm.expectRevert(abi.encodeWithSelector(TiwalaAgentWallet.WrongStatus.selector, TiwalaAgentWallet.Status.Locked));
        w.confirmDelivery(id);
        vm.expectRevert(abi.encodeWithSelector(TiwalaAgentWallet.WrongStatus.selector, TiwalaAgentWallet.Status.Locked));
        w.raiseDispute(id);
        vm.expectRevert(abi.encodeWithSelector(TiwalaAgentWallet.WrongStatus.selector, TiwalaAgentWallet.Status.Locked));
        w.resolveDispute(id, true);
        w.cancelDeal(id);
        vm.expectRevert(abi.encodeWithSelector(TiwalaAgentWallet.WrongStatus.selector, TiwalaAgentWallet.Status.Refunded));
        w.approveDeal(id);
        vm.expectRevert(abi.encodeWithSelector(TiwalaAgentWallet.WrongStatus.selector, TiwalaAgentWallet.Status.Refunded));
        w.extendDeadline(id, uint64(block.timestamp + 30 days));
        vm.stopPrank();
    }

    function test_FactoryLinkingRules() public {
        vm.expectRevert(TiwalaFactory.NoAccounts.selector);
        factory.createWallet(address(token), stranger, agent, 1, 1, 1, 0, new bytes32[](0));
        bytes32[] memory zero = new bytes32[](1);
        vm.expectRevert(TiwalaFactory.EmptyHash.selector);
        factory.linkAccounts(address(w), zero);
        vm.expectRevert(TiwalaFactory.UnknownWallet.selector);
        factory.linkAccounts(stranger, _h("maya:x"));
        factory.linkAccounts(address(w), _h("bpi:owner"));
        assertEq(factory.walletOfAccount(keccak256("bpi:owner")), address(w));
        factory.setPlatform(stranger);
        vm.expectRevert(TiwalaFactory.NotPlatform.selector);
        factory.linkAccounts(address(w), _h("maya:y"));
    }

    function test_OnlyIssuerMintsOrBurns() public {
        vm.prank(stranger);
        vm.expectRevert();
        token.mint(stranger, 1);
        assertEq(token.decimals(), 2);
    }

    // ---------------- fuzz: agent can never get more than maxDownBps out before attestation ----------------

    function testFuzz_AgentPreDeliveryOutflowBounded(uint256 total, uint16 bps) public {
        total = bound(total, 1, APPROVAL);
        bps = uint16(bound(bps, 0, 5000));
        uint256 id = _deal(total, bps);
        vm.prank(agent);
        w.releaseDownPayment(id);
        assertLe(token.balanceOf(supplier), (total * w.maxDownBps()) / 10000);
    }
}
