// Startup API follows https://gpui-kit.com/docs/getting-started/ (Apache-2.0 code examples).
use gpui_kit::*;
use gpui_kit::component::{button::{Button, ButtonVariants}, label::Label};
struct Smoke { clicks: usize }
impl Render for Smoke {
    fn render(&mut self, _: &mut Window, cx: &mut Context<Self>) -> impl IntoElement {
        div().flex().flex_col().size_full().items_center().justify_center().gap_3()
            .child(Label::new("Finsec GPUI - MOCK / NO DEVICE"))
            .child(Label::new(format!("클릭 확인: {}", self.clicks)))
            .child(Button::new("count").primary().label("확인 / Verify").on_click(cx.listener(|this, _, _, cx| {
                this.clicks += 1;
                cx.notify();
            })))
    }
}
fn main() {
    application().with_assets(assets::Assets).run(|cx| {
        init(cx);
        open_window(WindowOptions::default(), cx, |_, cx| cx.new(|_| Smoke { clicks: 0 }))
            .expect("native smoke window");
    });
}
