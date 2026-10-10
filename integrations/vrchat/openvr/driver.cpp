// Model poses enter the normal OpenVR driver API. No VRChat process hooks.
#include <winsock2.h>
#include <ws2tcpip.h>
#include <dxgi1_2.h>
#include <d3d11.h>
#include <wrl/client.h>
#include <openvr_driver.h>
#include <array>
#include <chrono>
#include <cmath>
#include <cstring>
#include <memory>
#include <thread>

namespace {
using Clock = std::chrono::steady_clock;
constexpr uint32_t PROTOCOL_VERSION=3; // explicit buttons and scroll axes
#pragma pack(push, 1)
struct PosePacket {
    char magic[4];
    uint32_t version;
    uint64_t session, sequence;
    double devices[3][7]; // xyz, xyzw in OpenVR standing space (metres)
    float hands[2][31][7]; // parent-relative xyz, xyzw
    uint32_t flags; // skeletons=1, left/right trigger=2/4, right system=8
    float scroll[2][2]; // left/right menu or action-menu axes
};
struct Ack {
    char magic[4] = {'V','G','A','1'};
    uint32_t version = PROTOCOL_VERSION;
    uint64_t session = 0, sequence = 0;
    uint32_t active = 0, skeleton = 0;
};
#pragma pack(pop)
static_assert(sizeof(PosePacket) == 1948);
static_assert(sizeof(Ack) == 32);

template<class T> bool validPose(const T* p, double positionLimit) {
    double norm = 0;
    for (int k=0;k<7;++k) if (!std::isfinite(p[k])) return false;
    for (int k=0;k<3;++k) if (std::abs(p[k]) > positionLimit) return false;
    for (int k=3;k<7;++k) norm += p[k]*p[k];
    return std::abs(norm - 1) < 0.02;
}
bool valid(const PosePacket& p) {
    if (std::memcmp(p.magic,"VGP1",4) || p.version != PROTOCOL_VERSION || (p.flags & ~0x3ffffu)) return false;
    for (const auto& axes:p.scroll) for (float axis:axes)
        if (!std::isfinite(axis) || std::abs(axis)>1) return false;
    for (const auto& d:p.devices) if (!validPose(d,20)) return false;
    if (p.flags & 1) for (const auto& h:p.hands)
        for (const auto& b:h) if (!validPose(b,1)) return false;
    return true;
}

class Display final : public vr::IVRDisplayComponent {
public:
    void GetWindowBounds(int32_t* x,int32_t* y,uint32_t* w,uint32_t* h) override {
        *x=0; *y=0; *w=960; *h=540;
    }
    bool IsDisplayOnDesktop() override { return false; }
    bool IsDisplayRealDisplay() override { return false; }
    void GetRecommendedRenderTargetSize(uint32_t* w,uint32_t* h) override { *w=960; *h=960; }
    void GetEyeOutputViewport(vr::EVREye eye,uint32_t* x,uint32_t* y,uint32_t* w,uint32_t* h) override {
        *x=eye==vr::Eye_Left?0:480; *y=0; *w=480; *h=540;
    }
    void GetProjectionRaw(vr::EVREye,float* l,float* r,float* t,float* b) override {
        *l=-1; *r=1; *t=-1; *b=1;
    }
    vr::DistortionCoordinates_t ComputeDistortion(vr::EVREye,float u,float v) override {
        vr::DistortionCoordinates_t c{};
        c.rfRed[0]=c.rfGreen[0]=c.rfBlue[0]=u;
        c.rfRed[1]=c.rfGreen[1]=c.rfBlue[1]=v;
        return c;
    }
    bool ComputeInverseDistortion(vr::HmdVector2_t*,vr::EVREye,uint32_t,float,float) override { return false; }
};

// Consume compositor frames without a physical display or desktop swapchain.
// The display redirect owns adapter selection (the HMD property alone does not
// select the compositor GPU in SteamVR's extended-desktop mode).
class VirtualDisplay final : public vr::ITrackedDeviceServerDriver, public vr::IVRVirtualDisplay {
    const Clock::time_point epoch=Clock::now();
    Microsoft::WRL::ComPtr<ID3D11Device> gpu;
    Microsoft::WRL::ComPtr<ID3D11DeviceContext> commands;
    Microsoft::WRL::ComPtr<ID3D11Texture2D> source, pixel;
    vr::SharedTextureHandle_t handle=0;
    bool pending=false;
public:
    vr::EVRInitError Activate(uint32_t id) override {
        auto properties=vr::VRProperties();
        const auto container=properties->TrackedDeviceToPropertyContainer(id);
        properties->SetStringProperty(container,vr::Prop_ModelNumber_String,"VIREA Virtual Display");
        const int selected=vr::VRSettings()->GetInt32("virea_pose","graphicsAdapterIndex");
        if(selected>=0) {
            Microsoft::WRL::ComPtr<IDXGIFactory1> factory;
            Microsoft::WRL::ComPtr<IDXGIAdapter1> adapter;
            if(FAILED(CreateDXGIFactory1(IID_PPV_ARGS(&factory))) ||
                FAILED(factory->EnumAdapters1(selected,&adapter))) return vr::VRInitError_Driver_Failed;
            DXGI_ADAPTER_DESC1 desc{};
            if(FAILED(adapter->GetDesc1(&desc))) return vr::VRInitError_Driver_Failed;
            const uint64_t luid=(uint64_t(uint32_t(desc.AdapterLuid.HighPart))<<32)|desc.AdapterLuid.LowPart;
            properties->SetUint64Property(container,vr::Prop_GraphicsAdapterLuid_Uint64,luid);
        }
        return vr::VRInitError_None;
    }
    void Deactivate() override { pixel.Reset(); source.Reset(); commands.Reset(); gpu.Reset(); handle=0; pending=false; }
    void EnterStandby() override {}
    void* GetComponent(const char* name) override {
        return !std::strcmp(name,vr::IVRVirtualDisplay_Version)?static_cast<vr::IVRVirtualDisplay*>(this):nullptr;
    }
    void DebugRequest(const char*,char* output,uint32_t size) override { if(size) output[0]=0; }
    vr::DriverPose_t GetPose() override { return {}; }
    void Present(const vr::PresentInfo_t* info,uint32_t size) override {
        if(!info || size<sizeof(*info)) return;
        if(!gpu) {
            Microsoft::WRL::ComPtr<IDXGIFactory1> factory;
            if(FAILED(CreateDXGIFactory1(IID_PPV_ARGS(&factory)))) return;
            for(UINT i=0;;++i) {
                Microsoft::WRL::ComPtr<IDXGIAdapter1> adapter;
                if(factory->EnumAdapters1(i,&adapter)==DXGI_ERROR_NOT_FOUND) break;
                Microsoft::WRL::ComPtr<ID3D11Device> device;
                Microsoft::WRL::ComPtr<ID3D11DeviceContext> context;
                if(FAILED(D3D11CreateDevice(adapter.Get(),D3D_DRIVER_TYPE_UNKNOWN,nullptr,0,
                    nullptr,0,D3D11_SDK_VERSION,&device,nullptr,&context))) continue;
                if(SUCCEEDED(device->OpenSharedResource(reinterpret_cast<HANDLE>(info->backbufferTextureHandle),
                    IID_PPV_ARGS(&source)))) { gpu=device; commands=context; break; }
            }
            if(!gpu) return;
        } else if(handle!=info->backbufferTextureHandle) {
            source.Reset();
            if(FAILED(gpu->OpenSharedResource(reinterpret_cast<HANDLE>(info->backbufferTextureHandle),
                IID_PPV_ARGS(&source)))) return;
        }
        handle=info->backbufferTextureHandle;
        if(!pixel) {
            D3D11_TEXTURE2D_DESC desc{}; source->GetDesc(&desc);
            desc.Width=desc.Height=desc.ArraySize=desc.MipLevels=1;
            desc.SampleDesc={1,0}; desc.Usage=D3D11_USAGE_STAGING;
            desc.BindFlags=desc.MiscFlags=0; desc.CPUAccessFlags=D3D11_CPU_ACCESS_READ;
            if(FAILED(gpu->CreateTexture2D(&desc,nullptr,&pixel))) return;
        }
        Microsoft::WRL::ComPtr<IDXGIKeyedMutex> mutex;
        source.As(&mutex);
        if(mutex && mutex->AcquireSync(0,5)!=S_OK) return;
        const D3D11_BOX box{0,0,0,1,1,1};
        commands->CopySubresourceRegion(pixel.Get(),0,0,0,0,source.Get(),0,&box);
        commands->Flush();
        if(mutex) mutex->ReleaseSync(0);
        pending=true;
    }
    void WaitForPresent() override {
        if(pending) {
            const auto deadline=Clock::now()+std::chrono::milliseconds(20);
            D3D11_MAPPED_SUBRESOURCE mapped{};
            while(Clock::now()<deadline) {
                const auto result=commands->Map(pixel.Get(),0,D3D11_MAP_READ,D3D11_MAP_FLAG_DO_NOT_WAIT,&mapped);
                if(SUCCEEDED(result)) { commands->Unmap(pixel.Get(),0); break; }
                if(result!=DXGI_ERROR_WAS_STILL_DRAWING) break;
                std::this_thread::sleep_for(std::chrono::milliseconds(1));
            }
            pending=false;
        }
        const auto seconds=std::chrono::duration<double>(Clock::now()-epoch).count();
        const auto next=std::chrono::duration<double>((std::floor(seconds*60)+1)/60);
        std::this_thread::sleep_until(epoch+std::chrono::duration_cast<Clock::duration>(next));
    }
    bool GetTimeSinceLastVsync(float* seconds,uint64_t* counter) override {
        const auto elapsed=std::chrono::duration<double>(Clock::now()-epoch).count();
        *counter=static_cast<uint64_t>(elapsed*60); *seconds=static_cast<float>(elapsed-*counter/60.0); return true;
    }
};

class CompositorProvider final : public vr::IVRCompositorPluginProvider {
    VirtualDisplay display;
public:
    vr::EVRInitError Init(vr::IVRDriverContext* context) override {
        VR_INIT_COMPOSITOR_DRIVER_CONTEXT(context); return vr::VRInitError_None;
    }
    void Cleanup() override { display.Deactivate(); VR_CLEANUP_COMPOSITOR_DRIVER_CONTEXT(); }
    const char* const* GetInterfaceVersions() override { return vr::k_InterfaceVersions; }
    void* GetComponent(const char* name) override { return display.GetComponent(name); }
};

class Device final : public vr::ITrackedDeviceServerDriver {
    int role;
    Display display;
    vr::DriverPose_t pose{};
    vr::VRInputComponentHandle_t skeleton=0, trigger=0, triggerValue=0, proximity=0, system=0;
    std::array<vr::VRInputComponentHandle_t,7> buttons{};
    std::array<vr::VRInputComponentHandle_t,2> scroll{};
public:
    uint32_t index=vr::k_unTrackedDeviceIndexInvalid;
    explicit Device(int deviceRole):role(deviceRole) {
        pose.qWorldFromDriverRotation.w=pose.qDriverFromHeadRotation.w=pose.qRotation.w=1;
        pose.vecPosition[1]=role==0?1.6:1.35;
        pose.vecPosition[0]=role==1?-0.6:role==2?0.6:0;
        pose.poseIsValid=pose.deviceIsConnected=true;
        pose.result=vr::TrackingResult_Running_OK;
    }
    vr::EVRInitError Activate(uint32_t id) override {
        index=vr::k_unTrackedDeviceIndexInvalid;
        auto p=vr::VRProperties();
        auto container=p->TrackedDeviceToPropertyContainer(id);
        // This is a generated virtual rig, not a measured Valve device. VRChat
        // consumes skeleton actions independently of controller identity.
        p->SetStringProperty(container,vr::Prop_ModelNumber_String,
            role==0?"VIREA Virtual HMD":"VIREA Generated Hand");
        p->SetStringProperty(container,vr::Prop_ManufacturerName_String,"VIREA");
        p->SetStringProperty(container,vr::Prop_TrackingSystemName_String,"virea_pose");
        p->SetStringProperty(container,vr::Prop_RegisteredDeviceType_String,
            role==0?"virea_pose/hmd":role==1?"virea_pose/left":"virea_pose/right");
        p->SetBoolProperty(container,vr::Prop_WillDriftInYaw_Bool,false);
        p->SetBoolProperty(container,vr::Prop_DeviceIsWireless_Bool,false);
        if (!role) {
            // Hybrid laptops may expose several adapters. A requested adapter
            // must be shared by SteamVR and the application; do not silently
            // fall back to another GPU after an invalid selection.
            const int adapterIndex=vr::VRSettings()->GetInt32("virea_pose","graphicsAdapterIndex");
            if(adapterIndex>=0) {
                IDXGIFactory1* factory=nullptr;
                if(FAILED(CreateDXGIFactory1(__uuidof(IDXGIFactory1),reinterpret_cast<void**>(&factory))))
                    return vr::VRInitError_Driver_Failed;
                IDXGIAdapter1* adapter=nullptr;
                const auto result=factory->EnumAdapters1(adapterIndex,&adapter);
                factory->Release();
                if(FAILED(result)) return vr::VRInitError_Driver_Failed;
                DXGI_ADAPTER_DESC1 desc{};
                const auto described=adapter->GetDesc1(&desc);
                adapter->Release();
                if(FAILED(described)) return vr::VRInitError_Driver_Failed;
                const uint64_t luid=(uint64_t(uint32_t(desc.AdapterLuid.HighPart))<<32)|desc.AdapterLuid.LowPart;
                p->SetUint64Property(container,vr::Prop_GraphicsAdapterLuid_Uint64,luid);
            }
            p->SetStringProperty(container,vr::Prop_RenderModelName_String,"generic_hmd");
            p->SetFloatProperty(container,vr::Prop_UserIpdMeters_Float,0.064f);
            p->SetFloatProperty(container,vr::Prop_DisplayFrequency_Float,60.f);
            p->SetFloatProperty(container,vr::Prop_SecondsFromVsyncToPhotons_Float,0.011f);
            p->SetFloatProperty(container,vr::Prop_UserHeadToEyeDepthMeters_Float,0.f);
            p->SetBoolProperty(container,vr::Prop_IsOnDesktop_Bool,false);
            p->SetBoolProperty(container,vr::Prop_DisplayDebugMode_Bool,false);
            p->SetUint64Property(container,vr::Prop_CurrentUniverseId_Uint64,42);
            p->SetBoolProperty(container,vr::Prop_ContainsProximitySensor_Bool,true);
            if(vr::VRDriverInput()->CreateBooleanComponent(container,"/proximity",&proximity)!=vr::VRInputError_None)
                return vr::VRInitError_Driver_Failed;
            vr::VRDriverInput()->UpdateBooleanComponent(proximity,true,0);
        } else {
            p->SetInt32Property(container,vr::Prop_ControllerRoleHint_Int32,
                role==1?vr::TrackedControllerRole_LeftHand:vr::TrackedControllerRole_RightHand);
            p->SetStringProperty(container,vr::Prop_ControllerType_String,"virea_generated_hand");
            p->SetStringProperty(container,vr::Prop_RenderModelName_String,
                "{virea_pose}virea_generated_hand");
            p->SetStringProperty(container,vr::Prop_InputProfilePath_String,
                "{virea_pose}/input/virea_generated_hand_profile.json");
            auto input=vr::VRDriverInput();
            if(input->CreateBooleanComponent(container,"/input/system/click",&system)!=vr::VRInputError_None ||
               input->CreateBooleanComponent(container,"/input/trigger/click",&trigger)!=vr::VRInputError_None ||
               input->CreateScalarComponent(container,"/input/trigger/value",&triggerValue,
                   vr::VRScalarType_Absolute,vr::VRScalarUnits_NormalizedOneSided)!=vr::VRInputError_None)
                return vr::VRInitError_Driver_Failed;
            const char* paths[]={"/input/quick/click","/input/main/click","/input/action/click",
                "/input/back/click","/input/grip/click","/input/drop/click","/input/scroll/click"};
            for(int i=0;i<7;++i)
                if(input->CreateBooleanComponent(container,paths[i],&buttons[i])!=vr::VRInputError_None)
                    return vr::VRInitError_Driver_Failed;
            for(int i=0;i<2;++i)
                if(input->CreateScalarComponent(container,i?"/input/scroll/y":"/input/scroll/x",&scroll[i],
                    vr::VRScalarType_Absolute,vr::VRScalarUnits_NormalizedTwoSided)!=vr::VRInputError_None)
                    return vr::VRInitError_Driver_Failed;
            const auto result=input->CreateSkeletonComponent(container,
                role==1?"/input/skeleton/left":"/input/skeleton/right",
                role==1?"/skeleton/hand/left":"/skeleton/hand/right","/pose/raw",
                // Model estimates are not measured Full hand tracking. Full
                // enables VRChat's pinch inputs, which conflict with explicit
                // menu clicks. Both ranges still receive all 31 model bones.
                vr::VRSkeletalTracking_Estimated,nullptr,0,&skeleton);
            if(result!=vr::VRInputError_None) return vr::VRInitError_Driver_Failed;
        }
        index=id;
        return vr::VRInitError_None;
    }
    void Deactivate() override { index=vr::k_unTrackedDeviceIndexInvalid; }
    void EnterStandby() override {}
    void* GetComponent(const char* name) override {
        return role==0 && !std::strcmp(name,vr::IVRDisplayComponent_Version)?&display:nullptr;
    }
    void DebugRequest(const char*,char* response,uint32_t size) override { if(size) response[0]=0; }
    vr::DriverPose_t GetPose() override { return pose; }
    bool update(const PosePacket& packet,bool fresh) {
        const auto& p=packet.devices[role];
        std::copy(p,p+3,pose.vecPosition);
        pose.qRotation={p[6],p[3],p[4],p[5]};
        // A stationary virtual device stays tracked between inference jobs.
        // Hold the last received transforms; never synthesize an idle animation.
        // The packet watchdog still releases every trigger when input expires.
        pose.result=vr::TrackingResult_Running_OK;
        if(index==vr::k_unTrackedDeviceIndexInvalid) return false;
        vr::VRServerDriverHost()->TrackedDevicePoseUpdated(index,pose,sizeof(pose));
        if (!role) {
            vr::VRDriverInput()->UpdateBooleanComponent(proximity,true,0);
            return false;
        }
        auto input=vr::VRDriverInput();
        input->UpdateBooleanComponent(system,fresh && role==2 && (packet.flags&8),0);
        const bool press=fresh && (packet.flags & (1u << role));
        input->UpdateBooleanComponent(trigger,press,0);
        input->UpdateScalarComponent(triggerValue,press?1.f:0.f,0);
        for(int i=0;i<7;++i)
            input->UpdateBooleanComponent(buttons[i],fresh && (packet.flags&(1u<<(4+2*i+role-1))),0);
        for(int i=0;i<2;++i) input->UpdateScalarComponent(scroll[i],fresh?packet.scroll[role-1][i]:0.f,0);
        if (!(packet.flags&1) || !skeleton) return false;
        vr::VRBoneTransform_t bones[31]{};
        for(int b=0;b<31;++b) {
            auto& value=packet.hands[role-1][b];
            bones[b].position={{value[0],value[1],value[2],1}};
            bones[b].orientation={value[6],value[3],value[4],value[5]};
        }
        auto a=input->UpdateSkeletonComponent(skeleton,vr::VRSkeletalMotionRange_WithController,bones,31);
        auto b=input->UpdateSkeletonComponent(skeleton,vr::VRSkeletalMotionRange_WithoutController,bones,31);
        return a==vr::VRInputError_None && b==vr::VRInputError_None;
    }
};

class GeneratedPoseDriver final : public vr::IServerTrackedDeviceProvider {
    SOCKET socket_=INVALID_SOCKET;
    std::array<std::unique_ptr<Device>,3> devices;
    std::unique_ptr<VirtualDisplay> display;
    PosePacket current{};
    Clock::time_point received=Clock::now();
    bool hasPacket=false, winsock=false;
public:
    vr::EVRInitError Init(vr::IVRDriverContext* context) override {
        VR_INIT_SERVER_DRIVER_CONTEXT(context);
        WSADATA data;
        if(WSAStartup(MAKEWORD(2,2),&data)) return vr::VRInitError_Driver_Failed;
        winsock=true;
        socket_=socket(AF_INET,SOCK_DGRAM,IPPROTO_UDP);
        sockaddr_in address{}; address.sin_family=AF_INET;
        address.sin_addr.s_addr=htonl(INADDR_LOOPBACK);
        int port=vr::VRSettings()->GetInt32("virea_pose","port");
        if(port<1024 || port>65535) { Cleanup(); return vr::VRInitError_Driver_Failed; }
        address.sin_port=htons(static_cast<u_short>(port));
        if(socket_==INVALID_SOCKET || bind(socket_,reinterpret_cast<sockaddr*>(&address),sizeof(address))) {
            Cleanup(); return vr::VRInitError_Driver_Failed;
        }
        u_long nonblocking=1; ioctlsocket(socket_,FIONBIO,&nonblocking);
        const char* serials[]={"VIREA-HMD-1","VIREA-LEFT-1","VIREA-RIGHT-1"};
        for(int i=0;i<3;++i) {
            devices[i]=std::make_unique<Device>(i);
            current.devices[i][1]=i==0?1.6:1.35;
            current.devices[i][0]=i==1?-0.6:i==2?0.6:0;
            current.devices[i][6]=1;
            vr::VRServerDriverHost()->TrackedDeviceAdded(serials[i],i==0?vr::TrackedDeviceClass_HMD:vr::TrackedDeviceClass_Controller,devices[i].get());
        }
        display=std::make_unique<VirtualDisplay>();
        vr::VRServerDriverHost()->TrackedDeviceAdded("VIREA-DISPLAY-1",vr::TrackedDeviceClass_DisplayRedirect,display.get());
        vr::VRDriverLog()->Log("VIREA generated-pose driver ready on loopback; no emote synthesis");
        return vr::VRInitError_None;
    }
    void Cleanup() override {
        for(auto& device:devices) device.reset();
        display.reset();
        if(socket_!=INVALID_SOCKET) { closesocket(socket_); socket_=INVALID_SOCKET; }
        if(winsock) { WSACleanup(); winsock=false; }
        VR_CLEANUP_SERVER_DRIVER_CONTEXT();
    }
    const char* const* GetInterfaceVersions() override { return vr::k_InterfaceVersions; }
    bool ShouldBlockStandbyMode() override { return true; }
    void EnterStandby() override {}
    void LeaveStandby() override {}
    void RunFrame() override {
        sockaddr_in sender{}; int senderLength=sizeof(sender); bool acknowledge=false;
        for(int n=0;n<32;++n) {
            PosePacket incoming;
            int count=recvfrom(socket_,reinterpret_cast<char*>(&incoming),sizeof(incoming),0,
                reinterpret_cast<sockaddr*>(&sender),&senderLength);
            if(count==SOCKET_ERROR) break;
            if(count!=sizeof(incoming) || !valid(incoming) || sender.sin_addr.s_addr!=htonl(INADDR_LOOPBACK)) continue;
            if(hasPacket && incoming.session==current.session && incoming.sequence<=current.sequence) continue;
            current=incoming; hasPacket=true; received=Clock::now(); acknowledge=true;
        }
        const bool fresh=!hasPacket || Clock::now()-received<std::chrono::milliseconds(750);
        Ack ack; ack.session=current.session; ack.sequence=current.sequence;
        for(int i=0;i<3;++i) if(devices[i]) {
            if(devices[i]->update(current,fresh)) ack.skeleton|=1u<<i;
            if(devices[i]->index!=vr::k_unTrackedDeviceIndexInvalid) ack.active|=1u<<i;
        }
        if(acknowledge) sendto(socket_,reinterpret_cast<const char*>(&ack),sizeof(ack),0,
            reinterpret_cast<sockaddr*>(&sender),senderLength);
        vr::VREvent_t event{};
        while(vr::VRServerDriverHost()->PollNextEvent(&event,sizeof(event))) {}
    }
};
GeneratedPoseDriver driver;
CompositorProvider compositor;
}
extern "C" __declspec(dllexport) void* HmdDriverFactory(const char* name,int* error) {
    if(!std::strcmp(name,vr::IServerTrackedDeviceProvider_Version)) return &driver;
    if(!std::strcmp(name,vr::IVRCompositorPluginProvider_Version)) return &compositor;
    if(error) *error=vr::VRInitError_Init_InterfaceNotFound;
    return nullptr;
}
