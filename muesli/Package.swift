// swift-tools-version:5.9
import PackageDescription

let package = Package(
    name: "Muesli",
    platforms: [.macOS(.v14)],
    targets: [
        .executableTarget(
            name: "Muesli",
            path: "Sources/Muesli"
        ),
        .testTarget(
            name: "MuesliTests",
            dependencies: ["Muesli"],
            path: "Tests/MuesliTests"
        ),
    ]
)
