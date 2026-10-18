// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {TiwalaAgentWallet} from "./TiwalaAgentWallet.sol";

/// @title Tiwala Factory
/// @notice Creates buyer wallets for onboarded MSMEs. The reputation indexer
///         reads events only from wallets this factory created, so a lookalike
///         contract emitting fake "completed" events is ignored.
///
///         Each wallet is bound to the salted hashes of the bank / e-wallet
///         accounts its owner linked at onboarding. One account can back only
///         one wallet, so a supplier cannot spin up several "buyers" from the
///         same GCash or bank account to inflate its distinct-buyer count.
///         Raw account numbers never touch the chain; the salt stays off-chain.
contract TiwalaFactory {
    error NotPlatform();
    error ZeroAddress();
    error NoAccounts();
    error UnknownWallet();
    error EmptyHash();
    error AccountAlreadyLinked(bytes32 accountHash, address wallet);

    address public platform;

    mapping(address => bool) public isWallet;
    mapping(bytes32 => address) public walletOfAccount;
    address[] public wallets;

    event WalletCreated(address indexed wallet, address indexed owner, address indexed agent, address token);
    event AccountLinked(address indexed wallet, bytes32 indexed accountHash);
    event PlatformChanged(address indexed platform);

    modifier onlyPlatform() {
        if (msg.sender != platform) revert NotPlatform();
        _;
    }

    constructor() {
        platform = msg.sender;
    }

    function setPlatform(address _platform) external onlyPlatform {
        if (_platform == address(0)) revert ZeroAddress();
        platform = _platform;
        emit PlatformChanged(_platform);
    }

    /// @param accountHashes salted hashes of the owner's linked accounts (at least one).
    function createWallet(
        address token,
        address owner,
        address agent,
        uint256 perDealCap,
        uint256 dailyCap,
        uint256 approvalThreshold,
        uint64 supplierDelay,
        bytes32[] calldata accountHashes
    ) external onlyPlatform returns (address wallet) {
        if (accountHashes.length == 0) revert NoAccounts();
        wallet = address(
            new TiwalaAgentWallet(token, owner, agent, perDealCap, dailyCap, approvalThreshold, supplierDelay)
        );
        isWallet[wallet] = true;
        wallets.push(wallet);
        emit WalletCreated(wallet, owner, agent, token);
        _link(wallet, accountHashes);
    }

    /// @notice Link more accounts to an existing wallet (owner added a new e-wallet).
    function linkAccounts(address wallet, bytes32[] calldata accountHashes) external onlyPlatform {
        if (!isWallet[wallet]) revert UnknownWallet();
        _link(wallet, accountHashes);
    }

    function walletCount() external view returns (uint256) {
        return wallets.length;
    }

    function _link(address wallet, bytes32[] calldata accountHashes) internal {
        for (uint256 i = 0; i < accountHashes.length; i++) {
            bytes32 h = accountHashes[i];
            if (h == bytes32(0)) revert EmptyHash();
            address existing = walletOfAccount[h];
            if (existing != address(0)) revert AccountAlreadyLinked(h, existing);
            walletOfAccount[h] = wallet;
            emit AccountLinked(wallet, h);
        }
    }
}
