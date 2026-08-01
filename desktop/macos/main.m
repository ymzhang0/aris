#import <Cocoa/Cocoa.h>
#import <WebKit/WebKit.h>

@interface ARISAppDelegate : NSObject <NSApplicationDelegate, WKNavigationDelegate>
@property(nonatomic, strong) NSWindow *window;
@property(nonatomic, strong) WKWebView *webView;
@property(nonatomic, strong) NSTextField *statusLabel;
@property(nonatomic, strong) NSButton *retryButton;
@property(nonatomic, strong) NSStackView *loadingView;
@property(nonatomic, strong) NSProgressIndicator *loadingSpinner;
@property(nonatomic, strong) NSTask *startupTask;
@property(nonatomic, strong) NSURL *arisURL;
@property(nonatomic) BOOL developmentMode;
@end

@implementation ARISAppDelegate

- (void)applicationDidFinishLaunching:(NSNotification *)notification {
    self.developmentMode = [[[NSProcessInfo processInfo] arguments] containsObject:@"--dev"];
    self.arisURL = [NSURL URLWithString:self.developmentMode
        ? @"http://127.0.0.1:5173/?desktop=1&dev=1"
        : @"http://127.0.0.1:8000/?desktop=1"];
    [self buildWindow];
    [self startARIS];
}

- (BOOL)applicationShouldTerminateAfterLastWindowClosed:(NSApplication *)sender {
    return YES;
}

- (void)buildWindow {
    NSRect frame = NSMakeRect(0, 0, 1360, 880);
    self.window = [[NSWindow alloc]
        initWithContentRect:frame
                  styleMask:NSWindowStyleMaskTitled | NSWindowStyleMaskClosable |
                            NSWindowStyleMaskMiniaturizable | NSWindowStyleMaskResizable |
                            NSWindowStyleMaskFullSizeContentView
                    backing:NSBackingStoreBuffered
                      defer:NO];
    self.window.title = self.developmentMode ? @"ARIS — Development" : @"ARIS";
    self.window.titleVisibility = NSWindowTitleHidden;
    self.window.titlebarAppearsTransparent = YES;
    self.window.movableByWindowBackground = NO;
    [self.window center];
    [self.window setFrameAutosaveName:@"ARISMainWindow"];

    WKWebViewConfiguration *configuration = [[WKWebViewConfiguration alloc] init];
    configuration.websiteDataStore = [WKWebsiteDataStore nonPersistentDataStore];
    self.webView = [[WKWebView alloc] initWithFrame:frame configuration:configuration];
    self.webView.navigationDelegate = self;
    self.window.contentView = self.webView;

    self.loadingView = [[NSStackView alloc] initWithFrame:NSZeroRect];
    self.loadingView.orientation = NSUserInterfaceLayoutOrientationVertical;
    self.loadingView.alignment = NSLayoutAttributeCenterX;
    self.loadingView.spacing = 12;
    self.loadingView.translatesAutoresizingMaskIntoConstraints = NO;

    self.loadingSpinner = [[NSProgressIndicator alloc] initWithFrame:NSZeroRect];
    self.loadingSpinner.style = NSProgressIndicatorStyleSpinning;
    self.loadingSpinner.controlSize = NSControlSizeRegular;
    [self.loadingSpinner startAnimation:nil];

    self.statusLabel = [NSTextField labelWithString:self.developmentMode
        ? @"正在启动 ARIS 开发环境…"
        : @"正在启动 ARIS…"];
    self.statusLabel.font = [NSFont systemFontOfSize:15 weight:NSFontWeightMedium];

    self.retryButton = [NSButton buttonWithTitle:@"重试"
                                          target:self
                                          action:@selector(retry:)];
    self.retryButton.hidden = YES;

    [self.loadingView addArrangedSubview:self.loadingSpinner];
    [self.loadingView addArrangedSubview:self.statusLabel];
    [self.loadingView addArrangedSubview:self.retryButton];
    [self.webView addSubview:self.loadingView];

    [NSLayoutConstraint activateConstraints:@[
        [self.loadingView.centerXAnchor constraintEqualToAnchor:self.webView.centerXAnchor],
        [self.loadingView.centerYAnchor constraintEqualToAnchor:self.webView.centerYAnchor],
    ]];

    [self.window makeKeyAndOrderFront:nil];
    [NSApp activateIgnoringOtherApps:YES];
}

- (void)retry:(id)sender {
    self.loadingView.hidden = NO;
    [self.loadingSpinner startAnimation:nil];
    self.retryButton.hidden = YES;
    self.statusLabel.stringValue = @"正在重新连接 ARIS…";
    [self startARIS];
}

- (void)startARIS {
    if (self.startupTask.running) {
        return;
    }

    NSString *repoPath = [[NSBundle mainBundle] objectForInfoDictionaryKey:@"ARISRepoPath"];
    if (repoPath.length == 0) {
        [self showFailure:@"应用缺少 ARISRepoPath 配置，请重新运行安装脚本。"];
        return;
    }

    NSString *launcher = [repoPath stringByAppendingPathComponent:@"scripts/aris-local.sh"];
    if (![[NSFileManager defaultManager] isExecutableFileAtPath:launcher]) {
        [self showFailure:[NSString stringWithFormat:@"找不到 ARIS 启动脚本：%@", launcher]];
        return;
    }

    NSTask *task = [[NSTask alloc] init];
    task.executableURL = [NSURL fileURLWithPath:@"/bin/zsh"];
    NSString *command = self.developmentMode ? @"dev" : @"start";
    task.arguments = @[@"-lc",
        [NSString stringWithFormat:@"\"%@\" %@", launcher, command]];
    NSPipe *output = [NSPipe pipe];
    task.standardOutput = output;
    task.standardError = output;
    self.startupTask = task;

    __weak typeof(self) weakSelf = self;
    task.terminationHandler = ^(NSTask *completedTask) {
        dispatch_async(dispatch_get_main_queue(), ^{
            if (completedTask.terminationStatus == 0) {
                [weakSelf loadARIS];
            } else {
                [weakSelf showFailure:
                    @"ARIS 启动失败。请运行 scripts/aris-local.sh doctor 查看详情。"];
            }
        });
    };

    NSError *error = nil;
    if (![task launchAndReturnError:&error]) {
        [self showFailure:[NSString stringWithFormat:@"无法启动 ARIS：%@",
                                                     error.localizedDescription]];
    }
}

- (void)loadARIS {
    self.statusLabel.stringValue = @"正在载入 ARIS…";
    NSURLRequest *request = [NSURLRequest
        requestWithURL:self.arisURL
           cachePolicy:NSURLRequestReloadIgnoringLocalCacheData
       timeoutInterval:30];
    [self.webView loadRequest:request];
}

- (void)showFailure:(NSString *)message {
    self.loadingView.hidden = NO;
    [self.loadingSpinner stopAnimation:nil];
    self.statusLabel.stringValue = message;
    self.retryButton.hidden = NO;
}

- (void)webView:(WKWebView *)webView didFinishNavigation:(WKNavigation *)navigation {
    [self.loadingSpinner stopAnimation:nil];
    self.loadingView.hidden = YES;
}

- (void)webView:(WKWebView *)webView
    didFailNavigation:(WKNavigation *)navigation
            withError:(NSError *)error {
    [self showFailure:[NSString stringWithFormat:@"无法连接 ARIS：%@",
                                                  error.localizedDescription]];
}

- (void)webView:(WKWebView *)webView
    didFailProvisionalNavigation:(WKNavigation *)navigation
                       withError:(NSError *)error {
    [self showFailure:[NSString stringWithFormat:@"无法连接 ARIS：%@",
                                                  error.localizedDescription]];
}

@end

int main(int argc, const char *argv[]) {
    @autoreleasepool {
        NSApplication *application = [NSApplication sharedApplication];
        ARISAppDelegate *delegate = [[ARISAppDelegate alloc] init];
        application.delegate = delegate;
        [application setActivationPolicy:NSApplicationActivationPolicyRegular];
        [application run];
    }
    return 0;
}
